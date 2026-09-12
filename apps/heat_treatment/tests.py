"""Heat Treatment as a furnace load: the batch, its label, and its screens.

The rule these tests defend is that grouping the *work* must not group the
*material*: a batch is several lots in one furnace, but each lot keeps its
own transaction and hands over to the next process on its own. Nothing
here names a stage - each test asks the registry which process this is and
what follows it.
"""

from decimal import Decimal
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from apps.heat_treatment import services as heat_services
from apps.heat_treatment.barcode import scan_url
from apps.heat_treatment.models import HeatBatch
from apps.masters import services as masters_services
from apps.masters.models import BatchNoFormat
from apps.production.process_registry import PROCESSES
from apps.production.test_process_screens import ProcessChainTestBase


class SeededHeatTestBase(ProcessChainTestBase):
    """The real master data (the batch number format lives there), with
    enough wire on the shelf for two batches: seeding rewrites the sample
    coils, so the fixture coil is re-issued afterwards."""

    def setUp(self):
        super().setUp()
        call_command("seed_masters", stdout=StringIO())
        self.coil = masters_services.receive_coil(
            raw_material=self.diameter, weight_kg=Decimal("1000.00"), rack=self.coil.rack
        )


class HeatBatchNumberTests(SeededHeatTestBase):
    """The number is validated from master data, not from code."""

    def test_a_number_is_normalized_and_checked_against_the_master_row(self):
        batch = heat_services.get_or_create_heat_batch(" b001 ", self.admin)
        self.assertEqual(batch.batch_no, "B001")

    def test_a_number_the_format_refuses_is_rejected(self):
        for bad in ("X1", "B1", "B12", "B00A", ""):
            with self.subTest(batch_no=bad):
                with self.assertRaises(ValidationError):
                    heat_services.get_or_create_heat_batch(bad, self.admin)

    def test_the_series_does_not_stop_at_three_digits(self):
        """B001 is the shape asked for, but the pattern allows more digits
        so the series does not wall at B999."""
        batch = heat_services.get_or_create_heat_batch("B1000", self.admin)
        self.assertEqual(batch.batch_no, "B1000")
        self.assertEqual(HeatBatch.objects.next_batch_no(), "B1001")

    def test_changing_the_master_row_changes_what_is_accepted(self):
        """The format is data: an admin can change it without a deploy."""
        fmt = BatchNoFormat.for_process(HeatBatch.process())
        fmt.regex, fmt.prefix, fmt.pad = r"^HL\d{4}$", "HL", 4
        fmt.save()
        self.assertEqual(heat_services.get_or_create_heat_batch("hl0007", self.admin).batch_no, "HL0007")
        with self.assertRaises(ValidationError):
            heat_services.get_or_create_heat_batch("B001", self.admin)

    def test_next_batch_no_continues_from_the_highest(self):
        self.assertEqual(HeatBatch.objects.next_batch_no(), "B001")
        heat_services.get_or_create_heat_batch("B004", self.admin)
        self.assertEqual(HeatBatch.objects.next_batch_no(), "B005")

    def test_next_batch_no_ignores_numbers_from_before_the_format(self):
        """Legacy numbers (HT-2604-001) are kept as history but are not part
        of this sequence, or the next number would be unusable."""
        HeatBatch.objects.create(batch_no="HT-2604-001")
        self.assertEqual(HeatBatch.objects.next_batch_no(), "B001")

    def test_an_existing_open_batch_is_reused(self):
        first = heat_services.get_or_create_heat_batch("B001", self.admin)
        self.assertEqual(heat_services.get_or_create_heat_batch("B001", self.admin).pk, first.pk)

    def test_a_completed_batch_cannot_be_reused(self):
        batch = heat_services.get_or_create_heat_batch("B001", self.admin)
        batch.status = "completed"
        batch.save(update_fields=["status"])
        with self.assertRaises(ValidationError) as caught:
            heat_services.get_or_create_heat_batch("B001", self.admin)
        self.assertIn("already completed", "; ".join(caught.exception.messages))


class HeatFlowTestBase(SeededHeatTestBase):
    """Two lots of different traveller types, walked to this process."""

    def setUp(self):
        super().setUp()
        self.process = heat_services.process()
        self.following = self.process.next

    # ------------------------------------------------------------------
    def two_lots_waiting(self):
        """Two lots of different traveller types, both waiting at this
        process, walked there through the real services."""
        from apps.masters.models import DiameterTravellerMapping, TravellerType

        other_type = TravellerType.objects.exclude(pk=self.rolling_batch.traveller_type.pk).first()
        DiameterTravellerMapping.objects.update_or_create(
            traveller_type=other_type,
            defaults={
                "raw_material": self.diameter,
                "f_thickness_mm": Decimal("0.41"),
                "f_width_mm": Decimal("1.78"),
            },
        )

        lots = []
        for traveller_type in (self.rolling_batch.traveller_type, other_type):
            self.rolling_batch.traveller_type = traveller_type
            record = self.complete_record(self.start_at_origin(), Decimal("390.00"))
            # Walk it up to - but not into - this process, so it is sitting
            # on the incoming list when the test starts.
            for step in range(1, self.process.index):
                record = self.initiate_via_screen(PROCESSES[step], record.handover_lot, Decimal("380.00"))
                record = self.complete_record(record, Decimal("380.00"))
            lots.append(record.handover_lot)
        return lots

    def waiting_lots(self):
        return {
            record.handover_lot.pk
            for record in self.process.incoming_queryset(None)
            if record.handover_lot
        }



class HeatBatchFlowTests(HeatFlowTestBase):
    """The services: one load, several lots, each handed over on its own."""

    def test_a_batch_takes_several_lots_of_different_traveller_types(self):
        lots = self.two_lots_waiting()
        self.assertTrue(self.waiting_lots().issuperset({lot.pk for lot in lots}))

        batch = heat_services.get_or_create_heat_batch("B001", self.admin)
        records = heat_services.initiate_heat_batch(batch, lots, self.admin)

        self.assertEqual(len(records), 2)
        self.assertEqual(batch.transactions.count(), 2)
        self.assertEqual(len(batch.traveller_types), 2, "The load must hold two traveller types")
        # Both have left the incoming list, because both are now in a
        # transaction here.
        self.assertFalse(self.waiting_lots() & {lot.pk for lot in lots})
        # The legacy column still reads the batch number, so anything that
        # reads it keeps working.
        for record in records:
            self.assertEqual(record.batch_number, batch.batch_no)

    def test_a_lot_that_is_not_waiting_here_is_refused_by_name(self):
        lots = self.two_lots_waiting()
        batch = heat_services.get_or_create_heat_batch("B001", self.admin)
        heat_services.initiate_heat_batch(batch, [lots[0]], self.admin)

        other = heat_services.get_or_create_heat_batch("B002", self.admin)
        with self.assertRaises(ValidationError) as caught:
            heat_services.initiate_heat_batch(other, [lots[0]], self.admin)
        self.assertIn(lots[0].wire_serial, "; ".join(caught.exception.messages))
        self.assertEqual(other.transactions.count(), 0, "Nothing may be written when one lot is refused")

    def test_completing_the_batch_hands_every_lot_over_on_its_own(self):
        lots = self.two_lots_waiting()
        batch = heat_services.get_or_create_heat_batch("B001", self.admin)
        heat_services.initiate_heat_batch(batch, lots, self.admin)

        outputs = {lots[0].pk: Decimal("370.00"), lots[1].pk: Decimal("360.00")}
        heat_services.complete_heat_batch(batch, outputs, self.admin)

        batch.refresh_from_db()
        self.assertEqual(batch.status, "completed")
        self.assertIsNotNone(batch.completed_at)
        self.assertTrue(batch.is_complete)

        waiting_next = {
            record.handover_lot.pk: record.output_weight
            for record in self.following.incoming_queryset(None)
            if record.handover_lot
        }
        for lot in lots:
            self.assertIn(lot.pk, waiting_next, f"{lot.wire_serial} did not reach {self.following.label}")
            self.assertEqual(waiting_next[lot.pk], outputs[lot.pk])

    def test_a_bad_output_weight_writes_nothing_at_all(self):
        lots = self.two_lots_waiting()
        batch = heat_services.get_or_create_heat_batch("B001", self.admin)
        heat_services.initiate_heat_batch(batch, lots, self.admin)

        with self.assertRaises(ValidationError):
            heat_services.complete_heat_batch(
                batch, {lots[0].pk: Decimal("370.00"), lots[1].pk: Decimal("9999.00")}, self.admin
            )
        batch.refresh_from_db()
        self.assertEqual(batch.status, "in_progress")
        self.assertEqual(batch.open_transactions.count(), 2, "No lot may finish while another is invalid")

    def test_a_missing_output_weight_names_the_lot(self):
        lots = self.two_lots_waiting()
        batch = heat_services.get_or_create_heat_batch("B001", self.admin)
        heat_services.initiate_heat_batch(batch, lots, self.admin)
        with self.assertRaises(ValidationError) as caught:
            heat_services.complete_heat_batch(batch, {lots[0].pk: Decimal("370.00")}, self.admin)
        self.assertIn(lots[1].wire_serial, "; ".join(caught.exception.messages))

    def test_a_transaction_without_a_batch_still_completes_on_its_own(self):
        """The per-lot screens predate batches and must keep working."""
        from apps.production import services as production_services

        lots = self.two_lots_waiting()
        record = production_services.initiate_stage(self.process, lots[0], self.admin)
        self.assertIsNone(record.heat_batch_id)

        record.output_quantity = Decimal("370.00")
        record.save(update_fields=["output_quantity"])
        production_services.complete_stage(record, self.admin)

        record.refresh_from_db()
        self.assertEqual(record.status, "completed")
        self.assertIn(
            lots[0].pk,
            {r.handover_lot.pk for r in self.following.incoming_queryset(None) if r.handover_lot},
        )


class HeatBatchScreenTests(HeatFlowTestBase):
    """The same flow, driven the way an operator drives it."""

    def test_the_initiate_screen_starts_a_batch_from_ticked_lots(self):
        lots = self.two_lots_waiting()
        url = reverse("heat_treatment:create")

        page = self.client.get(f"{url}?lot={lots[0].pk}")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "B001")  # the suggested next number
        self.assertContains(page, lots[1].wire_serial)  # the other waiting lot is offered

        response = self.client.post(url, {
            "batch_no": "b001",
            "operation_date": "2026-09-12",
            "lots": [str(lot.pk) for lot in lots],
        })
        batch = HeatBatch.objects.get(batch_no="B001")
        self.assertRedirects(
            response, reverse("heat_treatment:batch_detail", kwargs={"batch_no": "B001"})
        )
        self.assertEqual(batch.transactions.count(), 2)

    def test_the_batch_page_completes_the_whole_load(self):
        lots = self.two_lots_waiting()
        batch = heat_services.get_or_create_heat_batch("B001", self.admin)
        heat_services.initiate_heat_batch(batch, lots, self.admin)

        page = self.client.get(reverse("heat_treatment:batch_detail", kwargs={"batch_no": "B001"}))
        self.assertEqual(page.status_code, 200)
        for lot in lots:
            self.assertContains(page, lot.wire_serial)

        response = self.client.post(
            reverse("heat_treatment:batch_complete", kwargs={"batch_no": "B001"}),
            {f"output-{lots[0].pk}": "370.00", f"output-{lots[1].pk}": "360.00"},
        )
        self.assertRedirects(response, reverse("heat_treatment:batch_detail", kwargs={"batch_no": "B001"}))
        batch.refresh_from_db()
        self.assertEqual(batch.status, "completed")

    def test_a_bad_weight_re_renders_the_page_instead_of_losing_the_rest(self):
        lots = self.two_lots_waiting()
        batch = heat_services.get_or_create_heat_batch("B001", self.admin)
        heat_services.initiate_heat_batch(batch, lots, self.admin)

        response = self.client.post(
            reverse("heat_treatment:batch_complete", kwargs={"batch_no": "B001"}),
            {f"output-{lots[0].pk}": "370.00", f"output-{lots[1].pk}": "9999"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cannot exceed the received weight")
        batch.refresh_from_db()
        self.assertEqual(batch.status, "in_progress")

    def test_the_complete_table_shows_the_batch_number_and_its_qr(self):
        lots = self.two_lots_waiting()
        batch = heat_services.get_or_create_heat_batch("B001", self.admin)
        heat_services.initiate_heat_batch(batch, lots, self.admin)
        heat_services.complete_heat_batch(
            batch, {lots[0].pk: Decimal("370.00"), lots[1].pk: Decimal("360.00")}, self.admin
        )

        response = self.client.get(reverse("process:complete", kwargs={"process": self.process.slug}))
        self.assertContains(response, "Batch No")
        self.assertContains(response, "B001")
        self.assertContains(response, reverse("scan_qr", kwargs={"token": batch.qr_token}))

    def test_the_main_table_completes_a_batched_row_through_its_batch(self):
        lots = self.two_lots_waiting()
        batch = heat_services.get_or_create_heat_batch("B001", self.admin)
        heat_services.initiate_heat_batch(batch, lots, self.admin)

        response = self.client.get(reverse("process:main", kwargs={"process": self.process.slug}))
        self.assertContains(response, reverse("heat_treatment:batch_detail", kwargs={"batch_no": "B001"}))


class HeatBatchLabelTests(SeededHeatTestBase):
    """The label, the QR it carries and where scanning it lands."""

    def setUp(self):
        super().setUp()
        self.batch = heat_services.get_or_create_heat_batch("B001", self.admin)

    @override_settings(SITE_BASE_URL="http://192.168.1.50:8000")
    def test_the_qr_carries_the_configured_base_url(self):
        url = scan_url(self.batch)
        self.assertEqual(url, f"http://192.168.1.50:8000/scan/{self.batch.qr_token}/")

        response = self.client.get(reverse("heat_treatment:batch_qr", kwargs={"batch_no": "B001"}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/svg+xml")
        body = response.content.decode()
        self.assertIn(url, body, "The SVG must say what it encodes")
        self.assertNotIn("127.0.0.1", body)

    @override_settings(SITE_BASE_URL="http://192.168.1.50:8000")
    def test_a_label_never_points_at_localhost_when_a_base_url_is_set(self):
        """A QR pointing at 127.0.0.1 can never be opened from a phone."""
        page = self.client.get(reverse("heat_treatment:batch_label", kwargs={"batch_no": "B001"}))
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertIn("192.168.1.50", body)
        self.assertNotIn("127.0.0.1", body)

    def test_scanning_a_label_lands_on_its_batch(self):
        response = self.client.get(reverse("scan", kwargs={"token": self.batch.qr_token}))
        self.assertRedirects(
            response, reverse("heat_treatment:batch_detail", kwargs={"batch_no": "B001"})
        )

    def test_an_unknown_token_is_a_404(self):
        self.assertEqual(self.client.get("/scan/not-a-real-token/").status_code, 404)

    def test_scanning_needs_a_login(self):
        self.client.logout()
        response = self.client.get(reverse("scan", kwargs={"token": self.batch.qr_token}))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])


class HeatBatchApiTests(HeatFlowTestBase):
    """The typeahead behind Locate me."""

    def setUp(self):
        super().setUp()
        self.lots = self.two_lots_waiting()
        self.batch = heat_services.get_or_create_heat_batch("B001", self.admin)
        heat_services.initiate_heat_batch(self.batch, self.lots, self.admin)

    def search(self, **params):
        response = self.client.get(reverse("api-heat-batch-list"), params)
        self.assertEqual(response.status_code, 200)
        return [row["batch_no"] for row in response.json()]

    def test_it_finds_a_batch_by_number(self):
        self.assertIn("B001", self.search(search="b00"))

    def test_an_exact_batch_number_comes_first(self):
        """Wire serials read SB274 and batch numbers read B274, so a
        scanned batch number also matches a wire that contains it; the
        thing scanned has to be the thing at the top."""
        self.assertEqual(self.search(search="B001")[0], "B001")

    def test_it_finds_a_batch_by_a_wire_serial_in_it(self):
        self.assertIn("B001", self.search(search=self.lots[0].wire_serial))

    def test_it_finds_a_batch_by_a_traveller_type_in_it(self):
        self.assertIn("B001", self.search(search=self.lots[0].traveller_type.name))

    def test_completed_lists_what_the_complete_table_shows(self):
        self.assertEqual(self.search(status="completed"), [])
        heat_services.complete_heat_batch(
            self.batch,
            {self.lots[0].pk: Decimal("370.00"), self.lots[1].pk: Decimal("360.00")},
            self.admin,
        )
        self.assertIn("B001", self.search(status="completed"))


class LocateModalTests(ProcessChainTestBase):
    def test_it_renders_for_a_signed_in_user(self):
        response = self.client.get(reverse("dashboard:overview"))
        self.assertContains(response, 'id="locateModal"')
        self.assertContains(response, "Locate me")

    def test_it_is_absent_for_anonymous_visitors(self):
        self.client.logout()
        response = self.client.get(reverse("accounts:login"))
        self.assertNotContains(response, 'id="locateModal"')


class MainTableButtonTests(ProcessChainTestBase):
    """Only the origin process can start work from nothing; everywhere else
    material arrives from the process before it."""

    def test_only_the_origin_process_offers_a_create_button(self):
        for process in PROCESSES:
            with self.subTest(process=process.slug):
                response = self.client.get(reverse("process:main", kwargs={"process": process.slug}))
                self.assertEqual(response.status_code, 200)
                offered = bool(response.context["create_url"])
                self.assertEqual(
                    offered, process.previous is None,
                    f"{process.label} should {'' if process.previous is None else 'not '}offer a create button",
                )

    def test_the_downstream_labels_are_gone_from_the_screen(self):
        for process in PROCESSES:
            if process.previous is None:
                continue
            with self.subTest(process=process.slug):
                response = self.client.get(reverse("process:main", kwargs={"process": process.slug}))
                self.assertNotContains(response, process.create_label)


class PageSizeTests(ProcessChainTestBase):
    """Every screen shows more than a screenful, and takes ?per_page=."""

    def test_process_tables_default_to_more_than_twenty_rows(self):
        from apps.common.views import DEFAULT_PAGE_SIZE

        self.assertGreater(DEFAULT_PAGE_SIZE, 20)
        response = self.client.get(reverse("process:main", kwargs={"process": PROCESSES[0].slug}))
        self.assertEqual(response.context["per_page"], DEFAULT_PAGE_SIZE)

    def test_per_page_is_honoured_and_bounded(self):
        url = reverse("process:main", kwargs={"process": PROCESSES[0].slug})
        self.assertEqual(self.client.get(url, {"per_page": 100}).context["per_page"], 100)
        # A hand-typed size cannot ask the database for everything.
        self.assertEqual(self.client.get(url, {"per_page": 100000}).context["per_page"], 50)
        self.assertEqual(self.client.get(url, {"per_page": "lots"}).context["per_page"], 50)

    def test_the_other_list_screens_take_the_same_parameter(self):
        from apps.common.views import DEFAULT_PAGE_SIZE

        for name in ("production:order_list", "production:lot_list", "inventory:wip_list",
                     "inventory:transaction_list", "audit:list"):
            with self.subTest(screen=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["per_page"], DEFAULT_PAGE_SIZE)
                self.assertEqual(
                    self.client.get(reverse(name), {"per_page": 25}).context["per_page"], 25
                )


class BatchRenumberTests(SeededHeatTestBase):
    """Legacy numbers become the B-series, in the order the furnace ran."""

    def test_it_renumbers_legacy_batches_oldest_first(self):
        from django.utils import timezone

        old = HeatBatch.objects.create(batch_no="HT-2604-001")
        older = HeatBatch.objects.create(batch_no="HT-2605-002")
        # The batches were written in one migration, so the order comes from
        # the work, not from the rows: fake that by dating their creation.
        HeatBatch.objects.filter(pk=older.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=2)
        )

        call_command("renumber_heat_batches", stdout=StringIO())

        self.assertEqual(
            list(HeatBatch.objects.order_by("batch_no").values_list("batch_no", flat=True)),
            ["B001", "B002"],
        )
        older.refresh_from_db()
        self.assertEqual(older.batch_no, "B001", "The oldest work takes the first number")

    def test_the_legacy_column_on_each_transaction_follows(self):
        batch = HeatBatch.objects.create(batch_no="HT-2604-001")
        call_command("renumber_heat_batches", stdout=StringIO())
        batch.refresh_from_db()
        self.assertEqual(batch.batch_no, "B001")
        for transaction in batch.transactions.all():
            self.assertEqual(transaction.batch_number, "B001")

    def test_a_dry_run_writes_nothing(self):
        HeatBatch.objects.create(batch_no="HT-2604-001")
        call_command("renumber_heat_batches", dry_run=True, stdout=StringIO())
        self.assertTrue(HeatBatch.objects.filter(batch_no="HT-2604-001").exists())

    def test_running_it_again_changes_nothing(self):
        HeatBatch.objects.create(batch_no="HT-2604-001")
        call_command("renumber_heat_batches", stdout=StringIO())
        call_command("renumber_heat_batches", stdout=StringIO())
        self.assertEqual(
            list(HeatBatch.objects.values_list("batch_no", flat=True)), ["B001"]
        )


class LocateBoxTests(ProcessChainTestBase):
    """The Locate box is one search field, and no camera."""

    def test_the_modal_has_a_search_box_and_no_camera(self):
        response = self.client.get(reverse("dashboard:overview"))
        self.assertContains(response, 'id="locateSearch"')
        self.assertNotContains(response, "locateScanStart")
        self.assertNotContains(response, "html5-qrcode")
