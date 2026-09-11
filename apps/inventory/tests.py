from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.accounts.models import User
from apps.master_data.models import Location, MaterialMaster, Plant, UnitOfMeasure

from . import services
from .models import RawMaterialStock, StockTransfer


class StockMovementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="root", email="root@example.com", password="x")
        self.uom = UnitOfMeasure.objects.create(code="KG", name="Kilogram")
        self.plant = Plant.objects.create(code="P1", name="Plant One")
        self.loc_a = Location.objects.create(plant=self.plant, code="A", name="Store A", location_type="store")
        self.loc_b = Location.objects.create(plant=self.plant, code="B", name="Store B", location_type="store")
        self.material = MaterialMaster.objects.create(material_code="RM-1", name="Steel", unit_of_measure=self.uom)

    def test_receive_and_consume_raw_material(self):
        services.receive_raw_material(self.material, Decimal("100"), location=self.loc_a, user=self.admin)
        stock = RawMaterialStock.objects.get(material=self.material, location=self.loc_a)
        self.assertEqual(stock.quantity, Decimal("100"))

        services.consume_raw_material(self.material, Decimal("40"), location=self.loc_a, user=self.admin)
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, Decimal("60"))

    def test_cannot_consume_more_than_available(self):
        services.receive_raw_material(self.material, Decimal("10"), location=self.loc_a, user=self.admin)
        with self.assertRaises(ValidationError):
            services.consume_raw_material(self.material, Decimal("50"), location=self.loc_a, user=self.admin)

    def test_stock_transfer_moves_quantity_between_locations(self):
        services.receive_raw_material(self.material, Decimal("100"), location=self.loc_a, user=self.admin)
        transfer = StockTransfer.objects.create(
            stock_type="raw_material", material=self.material, from_location=self.loc_a, to_location=self.loc_b,
            quantity=Decimal("30"),
        )
        services.transfer_stock(transfer, user=self.admin)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, "completed")
        self.assertEqual(
            RawMaterialStock.objects.get(material=self.material, location=self.loc_a).quantity, Decimal("70")
        )
        self.assertEqual(
            RawMaterialStock.objects.get(material=self.material, location=self.loc_b).quantity, Decimal("30")
        )

    def test_negative_stock_prevented(self):
        stock = RawMaterialStock(material=self.material, location=self.loc_a, quantity=Decimal("-5"))
        with self.assertRaises(ValidationError):
            stock.full_clean()
