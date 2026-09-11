import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.finished_goods import services as fg_services
from apps.finishing.models import FinishingTransaction
from apps.forming.models import FormingTransaction
from apps.heat_treatment.models import HeatTreatmentTransaction
from apps.inventory import services as inv_services
from apps.inventory.models import FinishedGoodsStock, WIPStock
from apps.master_data.models import (
    Department, Employee, Location, Machine, MaterialMaster, Plant, ProductMaster, Shift, UnitOfMeasure,
)
from apps.masters.models import SurfaceFinish, TravellerNo, TravellerType
from apps.rolling.models import RollingBatch

from . import services as prod_services
from .models import ProductionLot, ProductionOrder


class WorkflowTestBase(TestCase):
    """Forming onward still runs on the generic ProductionLot/WIPStock
    pipeline. Rolling now feeds it via its own wire-serial/coil module (see
    apps.rolling.tests), so these tests seed the Forming-stage WIP directly
    to stand in for a completed rolling batch."""

    def setUp(self):
        self.admin = User.objects.create_superuser(username="root", email="root@example.com", password="x")

        self.uom = UnitOfMeasure.objects.create(code="KG", name="Kilogram")
        self.plant = Plant.objects.create(code="P1", name="Plant One")
        self.wip_location = Location.objects.create(plant=self.plant, code="WIP1", name="WIP Area", location_type="wip")
        self.fg_location = Location.objects.create(plant=self.plant, code="FG1", name="FG Store", location_type="fg")

        self.material = MaterialMaster.objects.create(
            material_code="RM-001", name="Steel Billet", unit_of_measure=self.uom, reorder_level=Decimal("10")
        )
        self.product = ProductMaster.objects.create(
            product_code="FG-001", name="Steel Rod", unit_of_measure=self.uom, raw_material=self.material
        )

        self.machine_forming = Machine.objects.create(code="M-FRM", name="Former", stage="forming", plant=self.plant)
        self.machine_ht = Machine.objects.create(code="M-HT", name="Furnace", stage="heat_treatment", plant=self.plant)
        self.machine_fin = Machine.objects.create(code="M-FIN", name="Polisher", stage="finishing", plant=self.plant)

        dept = Department.objects.create(plant=self.plant, code="PROD", name="Production")
        self.employee = Employee.objects.create(employee_code="E1", first_name="Op", department=dept)
        self.shift = Shift.objects.create(code="A", name="Morning", start_time=datetime.time(6, 0), end_time=datetime.time(14, 0))

        self.order = ProductionOrder.objects.create(product=self.product, planned_quantity=Decimal("1000"), uom="KG")

        # Wire Serial is mandatory downstream, so every test lot must carry
        # one via a (minimal, directly-created) completed Rolling batch -
        # these tests only exercise Forming onward, not Rolling itself
        # (see apps.rolling.tests for Rolling-specific coverage).
        traveller_type = TravellerType.objects.create(seq_no=1, name="U1UM UDR")
        traveller_no = TravellerNo.objects.create(code="1/0", label="1/0")
        finish = SurfaceFinish.objects.create(finish_name="Indigo")
        self.rolling_batch = RollingBatch.objects.create(
            wire_serial="TESTWS01", traveller_type=traveller_type, traveller_no=traveller_no, finish=finish,
            wire_diameter_mm=Decimal("0.93"), f_thickness_mm=Decimal("0.41"), f_width_mm=Decimal("1.78"),
            required_box=1, wire_weight_issued_kg=Decimal("500"), status="Completed",
            finished_weight_kg=Decimal("500"), completed_at=timezone.now(),
        )
        self.lot = ProductionLot.objects.create(
            production_order=self.order, quantity=Decimal("500"), source_rolling_batch=self.rolling_batch
        )

    def seed_forming_wip(self, quantity="500"):
        """Stand-in for rolling having completed and staged its output."""
        inv_services.add_wip("forming", self.lot, Decimal(quantity), user=self.admin, location=self.wip_location)
        self.lot.current_stage = "forming"
        self.lot.save(update_fields=["current_stage"])

    def make_lot(self, wire_serial, quantity):
        """A second (third, fourth...) lot, carried by its own completed
        Rolling batch and with its Forming WIP already staged."""
        batch = RollingBatch.objects.create(
            wire_serial=wire_serial, traveller_type=self.rolling_batch.traveller_type,
            traveller_no=self.rolling_batch.traveller_no, finish=self.rolling_batch.finish,
            wire_diameter_mm=Decimal("0.93"), f_thickness_mm=Decimal("0.41"), f_width_mm=Decimal("1.78"),
            required_box=1, wire_weight_issued_kg=quantity, status="Completed",
            finished_weight_kg=quantity, completed_at=timezone.now(),
        )
        lot = ProductionLot.objects.create(
            production_order=self.order, quantity=quantity, source_rolling_batch=batch,
            current_stage="forming",
        )
        inv_services.add_wip("forming", lot, quantity, user=self.admin, location=self.wip_location)
        return lot

    def make_forming(self, input_qty="500", output_qty="480", rejection_qty="15", status="in_progress"):
        return FormingTransaction.objects.create(
            lot=self.lot, machine=self.machine_forming, operator=self.employee, shift=self.shift,
            start_time=timezone.now(), input_quantity=Decimal(input_qty), output_quantity=Decimal(output_qty),
            rejection_quantity=Decimal(rejection_qty), status=status, created_by=self.admin, updated_by=self.admin,
        )


class ProductionOrderLotTests(WorkflowTestBase):
    def test_order_number_generated(self):
        self.assertTrue(self.order.order_number.startswith("PO-"))

    def test_lot_number_generated(self):
        self.assertTrue(self.lot.lot_number.startswith("LOT-"))

    def test_duplicate_stage_completion_prevented(self):
        self.seed_forming_wip("500")
        forming = self.make_forming()
        prod_services.complete_stage(forming, self.admin)
        forming.refresh_from_db()
        self.assertEqual(forming.status, "completed")
        with self.assertRaises(ValidationError):
            prod_services.complete_stage(forming, self.admin)


class QuantityValidationTests(WorkflowTestBase):
    def test_input_quantity_must_be_positive(self):
        forming = self.make_forming(input_qty="0", output_qty="0", rejection_qty="0")
        with self.assertRaises(ValidationError):
            forming.full_clean()

    def test_output_plus_rejection_cannot_exceed_input(self):
        forming = self.make_forming(input_qty="100", output_qty="90", rejection_qty="20")
        with self.assertRaises(ValidationError):
            forming.full_clean()


class FullPipelineTests(WorkflowTestBase):
    def test_full_pipeline_and_stock_movement(self):
        self.seed_forming_wip("480")

        forming = self.make_forming(input_qty="480", output_qty="460", rejection_qty="15")
        prod_services.complete_stage(forming, self.admin)
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.current_stage, "heat_treatment")
        self.assertEqual(WIPStock.objects.get(stage="heat_treatment", lot=self.lot).quantity, Decimal("460"))

        heat_treat = HeatTreatmentTransaction.objects.create(
            lot=self.lot, heat_treatment_type="normalizing", temperature_celsius=Decimal("850"),
            holding_time_minutes=Decimal("30"), machine=self.machine_ht, operator=self.employee, shift=self.shift,
            start_time=timezone.now(), input_quantity=Decimal("460"), output_quantity=Decimal("440"),
            rejection_quantity=Decimal("15"), status="in_progress", created_by=self.admin, updated_by=self.admin,
        )
        prod_services.complete_stage(heat_treat, self.admin)
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.current_stage, "finishing")

        finishing = FinishingTransaction.objects.create(
            lot=self.lot, machine=self.machine_fin, operator=self.employee, shift=self.shift,
            start_time=timezone.now(), input_quantity=Decimal("440"), output_quantity=Decimal("420"),
            rejection_quantity=Decimal("15"), status="in_progress", created_by=self.admin, updated_by=self.admin,
        )
        prod_services.complete_stage(finishing, self.admin)
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
        self.assertEqual(FinishingTransaction.objects.filter(lot=self.lot).count(), 1)
        self.assertEqual(FinishedGoodsStock.objects.filter(lot=self.lot).count(), 1)

        # Audit trail exists for the completion actions.
        self.assertTrue(AuditLog.objects.filter(action="complete", entity_type="FinishingTransaction").exists())
        self.assertTrue(AuditLog.objects.filter(action="approve", entity_type="FinishedGoodsStock").exists())

    def test_insufficient_wip_stock_blocks_consumption(self):
        self.seed_forming_wip("100")
        forming = self.make_forming(input_qty="500", output_qty="480", rejection_qty="15")
        with self.assertRaises(ValidationError):
            prod_services.complete_stage(forming, self.admin)

    def test_finished_goods_requires_quality_approval_to_be_available(self):
        fg_stock = FinishedGoodsStock(
            product=self.product, lot=self.lot, location=self.fg_location,
            accepted_quantity=Decimal("10"), rejected_quantity=Decimal("0"), status="available",
        )
        with self.assertRaises(ValidationError):
            fg_stock.full_clean()
