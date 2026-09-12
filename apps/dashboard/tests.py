"""The header scan is the only search box in the product.

The process tables and the rack screens no longer carry one of their own,
so everything an operator can scan has to land somewhere useful from here:
a wire serial on the process that is holding the material right now, a
slot label on its rack zone, and anything a process declares searchable on
that process's table.
"""

from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.urls import reverse

from apps.masters import services as rack_services
from apps.production.process_registry import PROCESSES, get_process
from apps.production.test_process_screens import ProcessChainTestBase


class GlobalScanTests(ProcessChainTestBase):
    def setUp(self):
        super().setUp()
        call_command("seed_masters", stdout=StringIO())
        self.coil = rack_services.receive_coil(
            raw_material=self.diameter, weight_kg=Decimal("500.00"), rack=self.coil.rack
        )

    def scan(self, term):
        return self.client.get(reverse("dashboard:search"), {"q": term})

    def main_table_of(self, process):
        return reverse("process:main", kwargs={"process": process.slug})

    def test_a_wire_serial_lands_on_the_process_that_holds_the_material(self):
        """The point of scanning at a machine: you get the table you are
        standing at, not the one the serial was born on."""
        record = self.complete_record(self.start_at_origin(), Decimal("390.00"))
        serial = record.wire_serial

        for process, following in zip(PROCESSES, PROCESSES[1:]):
            with self.subTest(at=following.slug):
                record = self.initiate_via_screen(following, record.handover_lot, Decimal("380.00"))
                response = self.scan(serial)
                self.assertRedirects(
                    response, f"{self.main_table_of(following)}?q={serial}", fetch_redirect_response=False
                )
                if following.next is not None:
                    record = self.complete_record(record, Decimal("380.00"))

    def test_a_partial_wire_serial_still_resolves_to_the_whole_one(self):
        record = self.complete_record(self.start_at_origin(), Decimal("390.00"))
        response = self.scan(record.wire_serial[1:])
        self.assertIn(record.wire_serial, response["Location"])

    def test_a_slot_label_opens_its_rack_zone_at_that_slot(self):
        record = self.complete_record(self.start_at_origin(), Decimal("390.00"))
        zone = rack_services.zone_for_process(PROCESSES[0])
        label = record.rack_slot_label
        self.assertTrue(label)

        response = self.scan(label)
        zone_url = reverse("masters:rack_zone", kwargs={"code": zone.code})
        self.assertEqual(response["Location"], f"{zone_url}#slot-{label}")

    def test_an_empty_slot_label_still_opens_its_zone(self):
        zone = rack_services.zone_for_process(PROCESSES[0])
        slot = rack_services.next_free_slot(zone)
        response = self.scan(slot.label.lower())
        self.assertIn(reverse("masters:rack_zone", kwargs={"code": zone.code}), response["Location"])

    def test_a_heat_batch_number_lands_on_heat_treatment(self):
        """A term only one process declares as searchable goes to that
        process - this is what the removed per-table search box did. Heat
        Treatment declares its furnace load's batch number."""
        from apps.heat_treatment import services as heat_services

        record = self.complete_record(self.start_at_origin(), Decimal("390.00"))
        process = get_process("heat_treatment")
        for following in PROCESSES[1:]:
            record = self.initiate_via_screen(following, record.handover_lot, Decimal("380.00"))
            if following is process:
                break
            record = self.complete_record(record, Decimal("380.00"))

        batch = heat_services.get_or_create_heat_batch("B999", self.admin)
        record.heat_batch = batch
        record.save(update_fields=["heat_batch", "batch_number"])

        self.assertRedirects(
            self.scan(batch.batch_no), f"{self.main_table_of(process)}?q={batch.batch_no}",
            fetch_redirect_response=False,
        )

    def test_nothing_found_returns_to_the_dashboard_with_a_message(self):
        response = self.client.get(reverse("dashboard:search"), {"q": "no-such-thing"}, follow=True)
        self.assertContains(response, "no-such-thing")

    def test_an_empty_scan_goes_back_to_the_dashboard(self):
        self.assertRedirects(self.scan("  "), reverse("dashboard:overview"), fetch_redirect_response=False)
