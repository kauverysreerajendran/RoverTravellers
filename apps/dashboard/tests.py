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

from apps.dashboard import services as dashboard_services
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


class DashboardOverviewTests(ProcessChainTestBase):
    """The overview is built from the registry, so it describes whatever
    processes exist rather than the five that exist today."""

    def test_the_flow_has_one_column_per_process_in_registry_order(self):
        flow = dashboard_services.flow_by_process(*dashboard_services.resolve_range("30d")[1:])
        self.assertEqual(
            [step["label"] for step in flow], [process.label for process in PROCESSES]
        )

    def test_every_chart_has_one_series_per_process(self):
        _, start, end = dashboard_services.resolve_range("30d")
        for name, chart in (
            ("throughput", dashboard_services.daily_throughput(start, end)),
            ("wastage", dashboard_services.wastage_trend()),
        ):
            with self.subTest(chart=name):
                self.assertEqual(
                    [series["label"] for series in chart["series"]],
                    [process.label for process in PROCESSES],
                )

    def test_weights_are_read_off_each_model_not_named_per_stage(self):
        """Two of the three weights are not columns anywhere: the terminal
        process records accepted and rejected rather than received, and the
        middle stages record no wastage - it is in less out."""
        for process in PROCESSES:
            with self.subTest(process=process.slug):
                fields = dashboard_services._fields(process.model)
                self.assertIsNotNone(fields["received"], "received weight is not derivable")
                self.assertIsNotNone(fields["output"], "output weight is not derivable")
                self.assertIsNotNone(fields["wastage"], "wastage is not derivable")
                self.assertIsNotNone(fields["completed"], "completion time is not derivable")

    def test_kpis_carry_a_value_a_label_and_a_comparison(self):
        _, start, end = dashboard_services.resolve_range("30d")
        kpis = dashboard_services.kpis(start, end)
        self.assertEqual(len(kpis), 4)
        for kpi in kpis:
            with self.subTest(kpi=kpi["key"]):
                self.assertIn("value", kpi)
                self.assertTrue(kpi["label"])
        wastage = next(kpi for kpi in kpis if kpi["key"] == "wastage")
        self.assertTrue(wastage["lower_is_better"])

    def test_an_unknown_range_falls_back_instead_of_failing(self):
        key, _, _ = dashboard_services.resolve_range("all-time")
        self.assertEqual(key, dashboard_services.DEFAULT_RANGE)

    def test_a_rack_bar_never_runs_past_its_end(self):
        """A bay can hold more than its nominal capacity; the bar stops at
        100% and the numbers say what really happened."""
        bar = dashboard_services._bar("Over", 471, 60)
        self.assertEqual(bar["pct"], 100.0)
        self.assertTrue(bar["over_capacity"])

    # ------------------------------------------------------------------
    def test_the_page_renders_for_every_range(self):
        for key in dashboard_services.RANGES:
            with self.subTest(range=key):
                response = self.client.get(reverse("dashboard:overview"), {"range": key})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["range"], key)

    def test_the_removed_panels_are_gone(self):
        response = self.client.get(reverse("dashboard:overview"))
        for panel in ("Production Orders", "Pending Quality Approvals", "Low Stock", "Recent Audit"):
            with self.subTest(panel=panel):
                self.assertNotContains(response, panel)

    def test_the_chart_data_is_handed_over_as_json_not_templated_into_js(self):
        response = self.client.get(reverse("dashboard:overview"))
        self.assertContains(response, 'id="dashboard-data"')
        self.assertContains(response, "application/json")

    def test_the_api_serves_the_same_payload(self):
        response = self.client.get(reverse("api-dashboard-overview"), {"range": "7d"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        for key in ("kpis", "flow", "throughput", "wastage", "traveller_mix", "racks", "completions"):
            self.assertIn(key, payload)
        self.assertEqual(payload["range"], "7d")

    def test_the_old_summary_endpoint_still_answers(self):
        """Kept intact: something else may still be reading it."""
        self.assertEqual(self.client.get(reverse("api-dashboard-summary")).status_code, 200)
