import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Role, User, UserRole
from apps.audit.models import AuditLog
from apps.finished_goods import services as fg_services
from apps.finishing.models import FinishingTransaction
from apps.forming.models import FormingTransaction
from apps.heat_treatment.models import HeatTreatmentTransaction
from apps.inventory import services as inv_services
from apps.inventory.models import FinishedGoodsStock, RawMaterialStock, WIPStock
from apps.master_data.models import (
    Employee, Location, Machine, MaterialMaster, Plant, ProductMaster, Shift, UnitOfMeasure,
)
from apps.rolling.models import RollingTransaction

from . import services as prod_services
from .models import ProductionLot, ProductionOrder


class WorkflowTestBase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="root", email="root@example.com", password="x")

        self.uom = UnitOfMeasure.objects.create(code="KG", name="Kilogram")
        self.plant = Plant.objects.create(code="P1", name="Plant One")
        self.rm_location = Location.objects.create(plant=self.plant, code="RM1", name="RM Store", location_type="store")
        self.fg_location = Location.objects.create(plant=self.plant, code="FG1", name="FG Store", location_type="fg")

        self.material = MaterialMaster.objects.create(
            material_code="RM-001", name="Steel Billet", unit_of_measure=self.uom, reorder_level=Decimal("10")
        )
        self.product = ProductMaster.objects.create(
            product_code="FG-001", name="Steel Rod", unit_of_measure=self.uom, raw_material=self.material
        )

        self.machine_rolling = Machine.objects.create(code="M-ROL", name="Roller", stage="rolling", plant=self.plant)
        self.machine_forming = Machine.objects.create(code="M-FRM", name="Former", stage="forming", plant=self.plant)
        self.machine_ht = Machine.objects.create(code="M-HT", name="Furnace", stage="heat_treatment", plant=self.plant)
        self.machine_fin = Machine.objects.create(code="M-FIN", name="Polisher", stage="finishing", plant=self.plant)

        dept = None
        from apps.master_data.models import Department

        dept = Department.objects.create(plant=self.plant, code="PROD", name="Production")
        self.employee = Employee.objects.create(employee_code="E1", first_name="Op", department=dept)
        self.shift = Shift.objects.create(code="A", name="Morning", start_time=datetime.time(6, 0), end_time=datetime.time(14, 0))

        self.order = ProductionOrder.objects.create(product=self.product, planned_quantity=Decimal("1000"), uom="KG")
        self.lot = ProductionLot.objects.create(production_order=self.order, quantity=Decimal("500"))

        inv_services.receive_raw_material(self.material, Decimal("1000"), location=self.rm_location, user=self.admin)

    def make_rolling(self, input_qty="500", output_qty="480", rejection_qty="15"):
        return RollingTransaction.objects.create(
            lot=self.lot, raw_material=self.material, machine=self.machine_rolling, operator=self.employee,
            shift=self.shift, start_time=timezone.now(), input_quantity=Decimal(input_qty),
            output_quantity=Decimal(output_qty), rejection_quantity=Decimal(rejection_qty), status="in_progress",
            created_by=self.admin, updated_by=self.admin,
        )


class ProductionOrderLotTests(WorkflowTestBase):
    def test_order_number_generated(self):
        self.assertTrue(self.order.order_number.startswith("PO-"))

    def test_lot_number_generated(self):
        self.assertTrue(self.lot.lot_number.startswith("LOT-"))

    def test_duplicate_lot_processing_prevented(self):
        rolling = self.make_rolling()
        prod_services.complete_rolling(rolling, self.admin, material=self.material, location=self.rm_location)
        rolling.refresh_from_db()
        self.assertEqual(rolling.status, "completed")
        with self.assertRaises(ValidationError):
            prod_services.complete_rolling(rolling, self.admin, material=self.material, location=self.rm_location)


class QuantityValidationTests(WorkflowTestBase):
    def test_input_quantity_must_be_positive(self):
        rolling = self.make_rolling(input_qty="0", output_qty="0", rejection_qty="0")
        with self.assertRaises(ValidationError):
            rolling.full_clean()

    def test_output_plus_rejection_cannot_exceed_input(self):
        rolling = self.make_rolling(input_qty="100", output_qty="90", rejection_qty="20")
        with self.assertRaises(ValidationError):
            rolling.full_clean()


class FullPipelineTests(WorkflowTestBase):
    def test_full_pipeline_and_stock_movement(self):
        rolling = self.make_rolling(input_qty="500", output_qty="480", rejection_qty="15")
        prod_services.complete_rolling(rolling, self.admin, material=self.material, location=self.rm_location)

        rm_stock = RawMaterialStock.objects.get(material=self.material, location=self.rm_location)
        self.assertEqual(rm_stock.quantity, Decimal("500"))

        wip_forming = WIPStock.objects.get(stage="forming", lot=self.lot)
        self.assertEqual(wip_forming.quantity, Decimal("480"))

        self.lot.refresh_from_db()
        self.assertEqual(self.lot.current_stage, "forming")

        forming = FormingTransaction.objects.create(
            lot=self.lot, machine=self.machine_forming, operator=self.employee, shift=self.shift,
            start_time=timezone.now(), input_quantity=Decimal("480"), output_quantity=Decimal("460"),
            rejection_quantity=Decimal("15"), status="in_progress", created_by=self.admin, updated_by=self.admin,
        )
        prod_services.complete_stage(forming, self.admin, current_stage="forming")
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.current_stage, "heat_treatment")
        self.assertEqual(WIPStock.objects.get(stage="heat_treatment", lot=self.lot).quantity, Decimal("460"))

        heat_treat = HeatTreatmentTransaction.objects.create(
            lot=self.lot, heat_treatment_type="normalizing", temperature_celsius=Decimal("850"),
            holding_time_minutes=Decimal("30"), machine=self.machine_ht, operator=self.employee, shift=self.shift,
            start_time=timezone.now(), input_quantity=Decimal("460"), output_quantity=Decimal("440"),
            rejection_quantity=Decimal("15"), status="in_progress", created_by=self.admin, updated_by=self.admin,
        )
        prod_services.complete_stage(heat_treat, self.admin, current_stage="heat_treatment")
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.current_stage, "finishing")

        finishing = FinishingTransaction.objects.create(
            lot=self.lot, machine=self.machine_fin, operator=self.employee, shift=self.shift,
            start_time=timezone.now(), input_quantity=Decimal("440"), output_quantity=Decimal("420"),
            rejection_quantity=Decimal("15"), status="in_progress", created_by=self.admin, updated_by=self.admin,
        )
        prod_services.complete_stage(finishing, self.admin, current_stage="finishing")
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.current_stage, "finished_goods")

        fg_stock = fg_services.receive_finished_goods(
            lot=self.lot, product=self.product, accepted_quantity=Decimal("400"), rejected_quantity=Decimal("20"),
            location=self.fg_location, rack=None, shelf=None, tray=None, user=self.admin,
        )
        self.assertEqual(fg_stock.status, "hold")
        self.assertFalse(fg_stock.quality_approved)

        fg_services.approve_finished_goods(fg_stock, self.admin)
        fg_stock.refresh_from_db()
        self.assertTrue(fg_stock.quality_approved)
        self.assertEqual(fg_stock.status, "available")

        # Traceability: full chain must be resolvable from the lot.
        self.assertEqual(RollingTransaction.objects.filter(lot=self.lot).count(), 1)
        self.assertEqual(FinishedGoodsStock.objects.filter(lot=self.lot).count(), 1)

        # Audit trail exists for the completion actions.
        self.assertTrue(AuditLog.objects.filter(action="complete", entity_type="RollingTransaction").exists())
        self.assertTrue(AuditLog.objects.filter(action="approve", entity_type="FinishedGoodsStock").exists())

    def test_insufficient_raw_material_blocks_consumption(self):
        rolling = self.make_rolling(input_qty="5000", output_qty="4800", rejection_qty="100")
        with self.assertRaises(ValidationError):
            prod_services.complete_rolling(rolling, self.admin, material=self.material, location=self.rm_location)

    def test_finished_goods_requires_quality_approval_to_be_available(self):
        fg_stock = FinishedGoodsStock(
            product=self.product, lot=self.lot, location=self.fg_location,
            accepted_quantity=Decimal("10"), rejected_quantity=Decimal("0"), status="available",
        )
        with self.assertRaises(ValidationError):
            fg_stock.full_clean()
