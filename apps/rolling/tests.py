from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.accounts.models import User
from apps.master_data.models import Location, Plant
from apps.masters.models import (
    CoilMaster, DiameterMaster, DiameterTravellerMapping, RackMaster, SurfaceFinish, TravellerNo, TravellerType,
    WireSerialMaster,
)
from apps.masters import services as masters_services

from . import services
from .models import RollingBatch


class RollingWorkflowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="root", email="root@example.com", password="x")
        self.traveller_type = TravellerType.objects.create(seq_no=1, name="U1M UDR")
        self.traveller_no = TravellerNo.objects.create(code="1", label="Pending label")
        self.finish = SurfaceFinish.objects.create(finish_name="Indigo")
        self.diameter = DiameterMaster.objects.create(raw_material_id="RM-093", diameter_mm=Decimal("0.93"))
        DiameterTravellerMapping.objects.create(
            traveller_type=self.traveller_type, raw_material=self.diameter,
            f_thickness_mm=Decimal("0.41"), f_width_mm=Decimal("1.78"),
        )
        # Three serials mirroring the master: SB110 already used, SB111/SB112 free.
        for order, (prefix, seq, status) in enumerate(
            [("SB", 110, "Used"), ("SB", 111, "Available"), ("SB", 112, "Available")], start=1110
        ):
            WireSerialMaster.objects.create(
                serial_no=WireSerialMaster.format_serial(prefix, seq),
                prefix=prefix, sequence=seq, sort_order=order, status=status,
            )
        self.rack = RackMaster.objects.create(rack_code="R1")
        self.coil1 = masters_services.receive_coil(raw_material=self.diameter, weight_kg=Decimal("22.00"), rack=self.rack)
        self.coil2 = masters_services.receive_coil(raw_material=self.diameter, weight_kg=Decimal("19.50"), rack=self.rack)

        # Completing a batch auto-stages its output as Forming WIP, which
        # needs a WIP location to exist.
        plant = Plant.objects.create(code="PLANT1", name="Test Plant")
        Location.objects.create(plant=plant, code="WIP-FORMING", name="Forming WIP Area", location_type="wip")

    def test_wire_serial_takes_next_available_from_master(self):
        self.assertEqual(masters_services.generate_wire_serial(), "SB111")
        self.assertEqual(
            WireSerialMaster.objects.get(serial_no="SB111").status, "Used"
        )

    def test_wire_serials_issue_in_order_without_reuse(self):
        self.assertEqual(masters_services.generate_wire_serial(), "SB111")
        self.assertEqual(masters_services.generate_wire_serial(), "SB112")

    def test_wire_serial_exhaustion_raises(self):
        masters_services.generate_wire_serial()
        masters_services.generate_wire_serial()
        with self.assertRaises(ValidationError):
            masters_services.generate_wire_serial()

    def test_serial_format_pads_to_two_digits(self):
        self.assertEqual(WireSerialMaster.format_serial("SA", 1), "SA01")
        self.assertEqual(WireSerialMaster.format_serial("SB", 110), "SB110")
        self.assertEqual(WireSerialMaster.format_serial("SC", 1000), "SC1000")

    def test_initiate_batch_single_coil(self):
        batch = services.initiate_rolling_batch(
            traveller_type=self.traveller_type, traveller_no=self.traveller_no, finish=self.finish,
            required_box=30, wire_weight_issued_kg=Decimal("18.00"),
            coil_weights=[(self.coil1.coil_id, Decimal("18.00"))], user=self.admin,
        )
        self.assertEqual(batch.wire_serial, "SB111")
        self.assertEqual(batch.wire_diameter_mm, Decimal("0.93"))
        self.assertEqual(batch.f_thickness_mm, Decimal("0.41"))
        self.assertEqual(batch.f_width_mm, Decimal("1.78"))
        self.coil1.refresh_from_db()
        self.assertEqual(self.coil1.weight_kg, Decimal("4.00"))
        self.assertEqual(self.coil1.status, "In Stock")

    def test_initiate_batch_multiple_coils_must_match_total(self):
        with self.assertRaises(ValidationError):
            services.initiate_rolling_batch(
                traveller_type=self.traveller_type, traveller_no=self.traveller_no, finish=self.finish,
                required_box=30, wire_weight_issued_kg=Decimal("18.00"),
                coil_weights=[(self.coil1.coil_id, Decimal("10.00")), (self.coil2.coil_id, Decimal("5.00"))],
                user=self.admin,
            )

    def test_coil_marked_consumed_when_fully_used(self):
        services.initiate_rolling_batch(
            traveller_type=self.traveller_type, traveller_no=self.traveller_no, finish=self.finish,
            required_box=30, wire_weight_issued_kg=Decimal("22.00"),
            coil_weights=[(self.coil1.coil_id, Decimal("22.00"))], user=self.admin,
        )
        self.coil1.refresh_from_db()
        self.assertEqual(self.coil1.status, "Consumed")
        self.diameter.refresh_from_db()
        self.assertEqual(self.diameter.active_coils, 1)  # only coil2 remains In Stock

    def test_cannot_take_more_than_coil_has(self):
        with self.assertRaises(ValidationError):
            services.initiate_rolling_batch(
                traveller_type=self.traveller_type, traveller_no=self.traveller_no, finish=self.finish,
                required_box=30, wire_weight_issued_kg=Decimal("50.00"),
                coil_weights=[(self.coil1.coil_id, Decimal("50.00"))], user=self.admin,
            )

    def test_missing_mapping_blocks_batch(self):
        other_type = TravellerType.objects.create(seq_no=2, name="U1UL UDR")
        with self.assertRaises(ValidationError):
            services.initiate_rolling_batch(
                traveller_type=other_type, traveller_no=self.traveller_no, finish=self.finish,
                required_box=30, wire_weight_issued_kg=Decimal("18.00"),
                coil_weights=[(self.coil1.coil_id, Decimal("18.00"))], user=self.admin,
            )

    def test_complete_batch_calculates_wastage(self):
        batch = services.initiate_rolling_batch(
            traveller_type=self.traveller_type, traveller_no=self.traveller_no, finish=self.finish,
            required_box=30, wire_weight_issued_kg=Decimal("18.00"),
            coil_weights=[(self.coil1.coil_id, Decimal("18.00"))], user=self.admin,
        )
        services.complete_rolling_batch(
            batch, rolled_thickness_mm=Decimal("0.41"), rolled_width_mm=Decimal("1.78"),
            finished_weight_kg=Decimal("17.20"), user=self.admin,
        )
        batch.refresh_from_db()
        self.assertEqual(batch.status, "Completed")
        self.assertEqual(batch.wastage_kg, Decimal("0.80"))

    def test_cannot_complete_batch_twice(self):
        batch = services.initiate_rolling_batch(
            traveller_type=self.traveller_type, traveller_no=self.traveller_no, finish=self.finish,
            required_box=30, wire_weight_issued_kg=Decimal("18.00"),
            coil_weights=[(self.coil1.coil_id, Decimal("18.00"))], user=self.admin,
        )
        services.complete_rolling_batch(
            batch, rolled_thickness_mm=Decimal("0.41"), rolled_width_mm=Decimal("1.78"),
            finished_weight_kg=Decimal("17.20"), user=self.admin,
        )
        with self.assertRaises(ValidationError):
            services.complete_rolling_batch(
                batch, rolled_thickness_mm=Decimal("0.41"), rolled_width_mm=Decimal("1.78"),
                finished_weight_kg=Decimal("17.20"), user=self.admin,
            )
