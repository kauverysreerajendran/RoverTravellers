from decimal import Decimal

from django.test import TestCase

from .models import MaterialMaster, ProductMaster, UnitOfMeasure


class MaterialCreationTests(TestCase):
    def setUp(self):
        self.uom = UnitOfMeasure.objects.create(code="KG", name="Kilogram")

    def test_material_creation(self):
        material = MaterialMaster.objects.create(
            material_code="RM-TEST-001", name="Test Billet", unit_of_measure=self.uom,
            reorder_level=Decimal("100.000"),
        )
        self.assertEqual(MaterialMaster.objects.count(), 1)
        self.assertTrue(material.is_active)

    def test_material_code_unique(self):
        MaterialMaster.objects.create(material_code="RM-DUP", name="A", unit_of_measure=self.uom)
        with self.assertRaises(Exception):
            MaterialMaster.objects.create(material_code="RM-DUP", name="B", unit_of_measure=self.uom)


class ProductCreationTests(TestCase):
    def test_product_creation(self):
        uom = UnitOfMeasure.objects.create(code="PCS", name="Pieces")
        product = ProductMaster.objects.create(product_code="FG-TEST-001", name="Test Rod", unit_of_measure=uom)
        self.assertEqual(ProductMaster.objects.count(), 1)
        self.assertEqual(str(product), "FG-TEST-001 - Test Rod")
