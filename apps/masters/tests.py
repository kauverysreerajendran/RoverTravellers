"""Storage rack zones: the grids material sits on between the processes.

Two kinds of coverage here. The first group is about the zones themselves
- a zone's slots exist as rows, they fill in a predictable order, a full
zone refuses more material and no lot ever holds two slots in one zone.
The second walks the real pipeline services and screens: completing at a
process places its output, initiating at the next one frees the slot, and
the terminal process keeps its stock on a slot until it is taken off
explicitly.

Nothing here names which process owns which zone; each test asks
`zone_for_process` about the process it is exercising, so a zone added for
a sixth process is covered by the same assertions.
"""

from decimal import Decimal
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.finished_goods import services as fg_services
from apps.masters import services as rack_services
from apps.masters.models import RackMaster, RackPlacement, RackSlot, RackZone, StorageRack
from apps.production.process_registry import PROCESSES
from apps.production.test_process_screens import ProcessChainTestBase


def make_zone(process_slug, *, code="TESTZ", name="Test Zone", racks=2, rows=2, columns=3, prefix="TZ"):
    zone = RackZone.objects.create(
        code=code, name=name, process_slug=process_slug, rack_count=racks, rows=rows, columns=columns
    )
    for position in range(1, racks + 1):
        StorageRack.objects.create(zone=zone, code=f"{prefix}-{position:02d}", position=position)
    return zone


class RackZoneTests(TestCase):
    """The zone as a physical grid, independent of any material."""

    def setUp(self):
        self.origin = PROCESSES[0]
        self.zone = make_zone(self.origin.slug)

    def test_a_rack_builds_every_slot_when_it_is_created(self):
        for rack in self.zone.racks.all():
            self.assertEqual(rack.slots.count(), self.zone.rows * self.zone.columns)
        self.assertEqual(self.zone.slots.count(), self.zone.total_slots)

    def test_slot_labels_read_as_rack_row_letter_column(self):
        rack = self.zone.racks.order_by("position").first()
        self.assertEqual(rack.slots.get(row=1, column=1).label, f"{rack.code}-A1")
        self.assertEqual(rack.slots.get(row=2, column=3).label, f"{rack.code}-B3")

    def test_a_zone_cannot_point_at_a_process_that_does_not_exist(self):
        with self.assertRaises(ValidationError):
            RackZone.objects.create(code="NOPE", name="Nowhere", process_slug="teleportation")

    def test_an_empty_zone_hands_out_its_very_first_slot(self):
        first = self.zone.slots.select_related("rack").order_by("rack__position", "row", "column").first()
        self.assertEqual(rack_services.next_free_slot(self.zone).pk, first.pk)
        self.assertEqual(rack_services.next_free_slot(self.zone).label, f"{first.rack.code}-A1")

    def test_zone_summary_reports_every_grid_position(self):
        summary = rack_services.zone_summary(self.zone)
        self.assertEqual(summary["total_racks"], self.zone.rack_count)
        self.assertEqual(summary["total_slots"], self.zone.total_slots)
        self.assertEqual(summary["empty"], self.zone.total_slots)
        self.assertEqual(summary["columns"], [1, 2, 3])
        for rack in summary["racks"]:
            self.assertEqual(len(rack["matrix"]), self.zone.rows)
            for row in rack["matrix"]:
                self.assertEqual(len(row["cells"]), self.zone.columns)
                self.assertTrue(all(cell["empty"] for cell in row["cells"]))


class RackPlacementServiceTests(ProcessChainTestBase):
    """Placement and release against real lots, with the zone attached to
    the origin process so one completed batch exercises it."""

    def setUp(self):
        super().setUp()
        self.origin = PROCESSES[0]
        self.zone = make_zone(self.origin.slug, racks=2, rows=2, columns=2)

    def lot_for(self, wire_serial="R-1"):
        return self.make_lot(wire_serial, Decimal("100"))

    def test_placing_puts_the_lot_on_the_first_free_slot_and_opens_history(self):
        lot = self.lot_for()
        slot = rack_services.place_lot(self.zone, lot, self.admin)

        self.assertEqual(slot.label, rack_services.slot_for_lot(self.zone, lot).label)
        placement = rack_services.open_placement(self.zone, lot)
        self.assertEqual(placement.slot_id, slot.pk)
        self.assertIsNone(placement.released_at)
        self.assertEqual(placement.placed_by, self.admin)

    def test_placing_the_same_lot_again_keeps_its_slot(self):
        lot = self.lot_for()
        first = rack_services.place_lot(self.zone, lot, self.admin)
        again = rack_services.place_lot(self.zone, lot, self.admin)
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(RackPlacement.objects.filter(lot=lot, released_at__isnull=True).count(), 1)

    def test_the_zone_fills_in_rack_then_row_then_column_order(self):
        expected = [
            slot.label
            for slot in self.zone.slots.select_related("rack").order_by("rack__position", "row", "column")
        ]
        taken = [
            rack_services.place_lot(self.zone, self.lot_for(f"ORDER-{index}"), self.admin).label
            for index in range(len(expected))
        ]
        self.assertEqual(taken, expected)

    def test_a_full_zone_refuses_more_material(self):
        for index in range(self.zone.total_slots):
            rack_services.place_lot(self.zone, self.lot_for(f"FULL-{index}"), self.admin)
        self.assertEqual(rack_services.zone_summary(self.zone)["empty"], 0)

        with self.assertRaises(ValidationError) as caught:
            rack_services.place_lot(self.zone, self.lot_for("OVERFLOW"), self.admin)
        self.assertIn("No empty slot", "; ".join(caught.exception.messages))

    def test_an_occupied_slot_cannot_be_picked(self):
        occupied = rack_services.place_lot(self.zone, self.lot_for("A"), self.admin)
        with self.assertRaises(ValidationError):
            rack_services.place_lot(self.zone, self.lot_for("B"), self.admin, slot=occupied)

    def test_a_lot_cannot_hold_two_slots_in_one_zone(self):
        lot = self.lot_for()
        rack_services.place_lot(self.zone, lot, self.admin)
        spare = self.zone.slots.filter(lot__isnull=True).first()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RackSlot.objects.filter(pk=spare.pk).update(lot=lot)

    def test_releasing_frees_the_slot_and_closes_its_history(self):
        lot = self.lot_for()
        slot = rack_services.place_lot(self.zone, lot, self.admin)

        released = rack_services.release_lot(self.zone, lot, self.admin, reason="picked up")
        self.assertEqual(released.pk, slot.pk)
        slot.refresh_from_db()
        self.assertIsNone(slot.lot_id)
        self.assertIsNone(slot.placed_at)
        self.assertIsNone(rack_services.open_placement(self.zone, lot))

        history = RackPlacement.objects.get(lot=lot)
        self.assertIsNotNone(history.released_at)
        self.assertEqual(history.released_reason, "picked up")
        self.assertEqual(rack_services.zone_summary(self.zone)["occupied"], 0)

    def test_releasing_material_that_was_never_placed_is_not_an_error(self):
        self.assertIsNone(rack_services.release_lot(self.zone, self.lot_for(), self.admin, reason="nothing"))


class SeededZoneTestBase(ProcessChainTestBase):
    """The real seeded zones (10 Forming racks, 5 Finished Goods racks)
    with one batch's worth of material to move through them."""

    def setUp(self):
        super().setUp()
        call_command("seed_masters", stdout=StringIO())
        # seed_masters rewrites the sample coils on RM-093 to the weights in
        # the Phase 1 document, so the fixture coil this suite draws 400 kg
        # from is re-issued afterwards.
        self.coil = rack_services.receive_coil(
            raw_material=self.diameter, weight_kg=Decimal("500.00"),
            rack=RackMaster.objects.order_by("rack_code").first(),
        )

    def zone_of(self, process):
        return rack_services.zone_for_process(process)


class RackFlowTests(SeededZoneTestBase):
    """The zones as the line actually uses them: completing places,
    initiating the next process releases, and the terminal process holds
    its slot until it is taken off."""

    def test_seeding_builds_both_zones_with_every_slot_empty(self):
        zones = RackZone.objects.filter(is_active=True)
        self.assertEqual(zones.count(), 2)
        for zone in zones:
            summary = rack_services.zone_summary(zone)
            self.assertEqual(summary["total_racks"], zone.rack_count)
            self.assertEqual(summary["total_slots"], zone.rack_count * zone.rows * zone.columns)
            self.assertEqual(summary["empty"], summary["total_slots"])

    def test_seeding_is_idempotent(self):
        before = RackSlot.objects.count()
        call_command("seed_masters", stdout=StringIO())
        self.assertEqual(RackSlot.objects.count(), before)

    def test_completing_at_the_origin_places_its_output_on_a_slot(self):
        origin = PROCESSES[0]
        zone = self.zone_of(origin)
        self.assertIsNotNone(zone, "The origin process must have a storage zone")

        record = self.complete_record(self.start_at_origin(), Decimal("390.00"))
        lot = record.handover_lot
        slot = rack_services.slot_for_lot(zone, lot)
        self.assertIsNotNone(slot, f"{record.wire_serial} was not placed on {zone.name}")
        self.assertEqual(record.rack_slot_label, slot.label)

    def test_the_operator_can_choose_the_slot_the_output_goes_on(self):
        origin = PROCESSES[0]
        zone = self.zone_of(origin)
        chosen = zone.slots.select_related("rack").order_by("-rack__position", "-row", "-column").first()

        batch = self.start_at_origin()
        response = self.client.post(
            reverse("rolling:complete", kwargs={"pk": batch.pk}),
            {
                "rolled_thickness_mm": "0.41", "rolled_width_mm": "1.78",
                "finished_weight_kg": "390.00", "rack_slot": str(chosen.pk),
            },
        )
        self.assertEqual(response.status_code, 302)
        batch.refresh_from_db()
        self.assertEqual(batch.rack_slot_label, chosen.label)

    def test_the_next_process_sees_the_slot_on_its_incoming_row(self):
        origin, following = PROCESSES[0], PROCESSES[1]
        record = self.complete_record(self.start_at_origin(), Decimal("390.00"))
        label = record.rack_slot_label
        self.assertTrue(label)

        response = self.client.get(reverse("process:main", kwargs={"process": following.slug}))
        self.assertContains(response, label)
        self.assertIn("Rack Slot", [column.label for column in following.main_columns])

    def test_initiating_the_next_process_frees_the_slot(self):
        origin, following = PROCESSES[0], PROCESSES[1]
        zone = self.zone_of(origin)
        record = self.complete_record(self.start_at_origin(), Decimal("390.00"))
        lot = record.handover_lot
        self.assertIsNotNone(rack_services.slot_for_lot(zone, lot))

        self.initiate_via_screen(following, lot, Decimal("390.00"))

        self.assertIsNone(rack_services.slot_for_lot(zone, lot))
        self.assertEqual(rack_services.zone_summary(zone)["occupied"], 0)
        placement = RackPlacement.objects.get(lot=lot)
        self.assertIsNotNone(placement.released_at)
        self.assertIn(following.label, placement.released_reason)

    def run_to_terminal(self):
        """Walk the registry to the terminal process, returning its record."""
        record = self.start_at_origin()
        output = Decimal("390.00")
        for process, following in zip(PROCESSES, PROCESSES[1:]):
            record = self.complete_record(record, output)
            output = (output - Decimal("10.00")).quantize(Decimal("0.01"))
            record = self.initiate_via_screen(following, record.handover_lot, output)
        return record

    def test_the_terminal_process_places_its_stock_and_holds_the_slot(self):
        terminal = PROCESSES[-1]
        zone = self.zone_of(terminal)
        self.assertIsNotNone(zone, "The terminal process must have a storage zone")

        stock = self.run_to_terminal()
        slot = rack_services.slot_for_lot(zone, stock.lot)
        self.assertIsNotNone(slot, "Received stock was not placed on a slot")
        self.assertEqual(stock.rack_slot_label, slot.label)
        self.assertIn("Rack Slot", [column.label for column in terminal.complete_columns])

        # Nothing follows it, so approving it must not free the slot.
        fg_services.approve_finished_goods(stock, self.admin, mark_available=True)
        self.assertEqual(rack_services.slot_for_lot(zone, stock.lot).pk, slot.pk)

    def test_removing_from_the_rack_frees_the_terminal_slot(self):
        terminal = PROCESSES[-1]
        zone = self.zone_of(terminal)
        stock = self.run_to_terminal()
        slot = rack_services.slot_for_lot(zone, stock.lot)

        response = self.client.post(reverse("finished_goods:remove_from_rack", kwargs={"pk": stock.pk}))
        self.assertEqual(response.status_code, 302)

        self.assertIsNone(rack_services.slot_for_lot(zone, stock.lot))
        self.assertIsNotNone(RackPlacement.objects.get(lot=stock.lot, slot=slot).released_at)

    def test_the_rolling_complete_table_shows_the_rack_slot(self):
        origin = PROCESSES[0]
        record = self.complete_record(self.start_at_origin(), Decimal("390.00"))
        response = self.client.get(reverse("process:complete", kwargs={"process": origin.slug}))
        self.assertContains(response, "Rack Slot")
        self.assertContains(response, record.rack_slot_label)


class RackScreenTests(SeededZoneTestBase):
    """The Rack screens: the coil bay keeps working, each zone gets a page."""

    def test_the_raw_material_tab_still_lists_the_coil_bay(self):
        response = self.client.get(reverse("masters:rack_locator"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Raw Material")
        self.assertContains(response, self.coil.rack.rack_code)
        self.assertContains(response, f"Coil {self.coil.coil_display_number}")

    def test_every_zone_has_a_tab_and_a_page_of_empty_slots(self):
        for zone in RackZone.objects.filter(is_active=True):
            with self.subTest(zone=zone.code):
                url = reverse("masters:rack_zone", kwargs={"code": zone.code})
                self.assertContains(self.client.get(reverse("masters:rack_locator")), url)

                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["total_slots"], zone.total_slots)
                self.assertEqual(response.context["empty"], zone.total_slots)
                self.assertEqual(response.context["total_racks"], zone.rack_count)
                for rack in zone.racks.all():
                    self.assertContains(response, rack.code)

    def test_a_zone_page_shows_the_material_on_its_slots(self):
        zone = rack_services.zone_for_process(PROCESSES[0])
        record = self.complete_record(self.start_at_origin(), Decimal("390.00"))

        response = self.client.get(reverse("masters:rack_zone", kwargs={"code": zone.code}))
        self.assertEqual(response.context["occupied"], 1)
        self.assertEqual(response.context["empty"], zone.total_slots - 1)
        self.assertContains(response, record.wire_serial)
        self.assertContains(response, record.rack_slot_label)

    def test_an_unknown_zone_code_is_a_404(self):
        self.assertEqual(self.client.get("/masters/racks/NOSUCH/").status_code, 404)


class AssignRackSlotsTests(SeededZoneTestBase):
    """The backfill for material that finished before the zones existed."""

    def place_history_without_zones(self):
        """Complete a batch, then wipe the placement so the database looks
        the way it did before the zones were introduced."""
        record = self.complete_record(self.start_at_origin(), Decimal("390.00"))
        RackSlot.objects.filter(lot=record.handover_lot).update(lot=None, placed_at=None, placed_by=None)
        RackPlacement.objects.all().delete()
        return record

    def test_it_places_material_that_finished_before_the_zones_existed(self):
        record = self.place_history_without_zones()
        zone = rack_services.zone_for_process(PROCESSES[0])
        self.assertIsNone(rack_services.slot_for_lot(zone, record.handover_lot))

        call_command("assign_rack_slots", stdout=StringIO())

        slot = rack_services.slot_for_lot(zone, record.handover_lot)
        self.assertIsNotNone(slot)
        first = zone.slots.select_related("rack").order_by("rack__position", "row", "column").first()
        self.assertEqual(slot.pk, first.pk, "The backfill fills the zone from its first slot")

    def test_running_it_again_places_nothing_new(self):
        self.place_history_without_zones()
        call_command("assign_rack_slots", stdout=StringIO())
        after_first = {
            (slot.pk, slot.lot_id) for slot in RackSlot.objects.exclude(lot__isnull=True)
        }
        placements = RackPlacement.objects.count()

        call_command("assign_rack_slots", stdout=StringIO())

        self.assertEqual(
            {(slot.pk, slot.lot_id) for slot in RackSlot.objects.exclude(lot__isnull=True)}, after_first
        )
        self.assertEqual(RackPlacement.objects.count(), placements)

    def test_an_unknown_zone_code_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command("assign_rack_slots", zone="NOSUCH", stdout=StringIO())
