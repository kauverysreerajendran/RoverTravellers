"""Regression tests for the configuration-driven process screens.

These cover the contract the registry promises: every registered process
gets a working Main Table and Complete Table, Wire Serial is always
shown, Lot never is, and the two tables are genuinely different screens.
"""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.forming.models import FormingTransaction
from apps.inventory import services as inv_services
from apps.production.process_registry import PROCESSES, get_process
from apps.production.tests import WorkflowTestBase


class ProcessRegistryTests(TestCase):
    def test_every_process_declares_both_column_sets(self):
        for process in PROCESSES:
            with self.subTest(process=process.slug):
                self.assertTrue(process.main_columns, "Main Table columns missing")
                self.assertTrue(process.complete_columns, "Complete Table columns missing")

    def test_wire_serial_is_present_in_every_table(self):
        """Wire Serial is mandatory for every data table."""
        for process in PROCESSES:
            for name in ("main_columns", "complete_columns"):
                labels = [column.label for column in getattr(process, name)]
                with self.subTest(process=process.slug, table=name):
                    self.assertIn("Wire Serial", labels)

    def test_no_table_exposes_a_lot_column(self):
        """The ProductionLot number must never surface in the UI - neither
        as a column heading nor as a rendered value. The database column
        itself is untouched; only the frontend hides it."""
        for process in PROCESSES:
            for name in ("main_columns", "complete_columns"):
                for column in getattr(process, name):
                    with self.subTest(process=process.slug, column=column.label):
                        self.assertNotRegex(column.label.lower(), r"(^|\W)lot(\W|$)")
                        self.assertNotIn("lot.lot_number", column.accessor)
                        self.assertNotIn("lot.lot_number", column.pending)

    def test_complete_table_is_richer_than_main_table(self):
        """The two submenus must not resolve to the same screen."""
        for process in PROCESSES:
            with self.subTest(process=process.slug):
                self.assertGreater(len(process.complete_columns), len(process.main_columns))

    def test_weight_labels_follow_the_agreed_convention(self):
        """Incoming weight reads "Finished Weight"; a process's own output
        reads "Output Weight" - never two identically-titled columns."""
        for process in PROCESSES:
            for name in ("main_columns", "complete_columns"):
                labels = [c.label for c in getattr(process, name)]
                with self.subTest(process=process.slug, table=name):
                    self.assertNotIn("Weight Received", labels)
                    self.assertNotIn("Received Weight (kg)", labels)
                    self.assertEqual(len([lbl for lbl in labels if lbl.startswith("Finished Weight")]),
                                     0 if process.slug == "rolling" else 1)

    def test_unknown_slug_is_not_registered(self):
        self.assertIsNone(get_process("does-not-exist"))


class ProcessScreenTests(WorkflowTestBase):
    """Every submenu destination must actually load, for real data."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_all_ten_screens_load(self):
        for process in PROCESSES:
            for submenu in ("main", "complete"):
                url = reverse(f"process:{submenu}", kwargs={"process": process.slug})
                with self.subTest(url=url):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, "Wire Serial")
                    self.assertContains(response, process.label)

    def test_screens_never_render_a_lot_number(self):
        self.seed_forming_wip("480")
        self.make_forming()
        for process in PROCESSES:
            for submenu in ("main", "complete"):
                url = reverse(f"process:{submenu}", kwargs={"process": process.slug})
                with self.subTest(url=url):
                    body = self.client.get(url).content.decode()
                    self.assertNotIn(self.lot.lot_number, body)

    def test_unknown_process_returns_404(self):
        response = self.client.get("/process/not-a-process/main/")
        self.assertEqual(response.status_code, 404)

    def test_legacy_list_urls_redirect_to_the_main_table(self):
        for slug in ("rolling", "forming", "heat_treatment", "finishing", "finished_goods"):
            with self.subTest(slug=slug):
                response = self.client.get(reverse(f"{slug}:list"))
                self.assertRedirects(
                    response, reverse("process:main", kwargs={"process": slug}), fetch_redirect_response=False
                )

    def test_sort_parameter_cannot_inject_an_arbitrary_orm_path(self):
        url = reverse("process:complete", kwargs={"process": "forming"})
        response = self.client.get(url, {"sort": "lot__production_order__product__name", "dir": "asc"})
        self.assertEqual(response.status_code, 200)

    def test_search_filters_rows(self):
        self.seed_forming_wip("480")
        transaction = self.make_forming()
        url = reverse("process:complete", kwargs={"process": "forming"})

        hit = self.client.get(url, {"q": transaction.transaction_number})
        self.assertContains(hit, transaction.transaction_number)

        miss = self.client.get(url, {"q": "NO-SUCH-RECORD"})
        self.assertNotContains(miss, transaction.transaction_number)
        self.assertContains(miss, "No records match this filter")

    def test_empty_process_shows_its_empty_state(self):
        response = self.client.get(reverse("process:complete", kwargs={"process": "finishing"}))
        self.assertContains(response, "No finishing records yet")

    def test_pending_row_shows_the_weight_the_previous_process_handed_over(self):
        """The pending Main Table row must read its weight from the WIP
        staged for this stage, not the lot's original quantity."""
        self.lot.current_stage = "heat_treatment"
        self.lot.save(update_fields=["current_stage"])
        inv_services.add_wip(
            "heat_treatment", self.lot, Decimal("123.456"), user=self.admin, location=self.wip_location
        )
        response = self.client.get(reverse("process:main", kwargs={"process": "heat_treatment"}))
        self.assertContains(response, "123.456")
        self.assertNotContains(response, str(self.lot.quantity))
        self.assertContains(response, "Initiate")

    def test_main_table_offers_an_action_for_every_row(self):
        self.seed_forming_wip("480")
        self.make_forming()
        response = self.client.get(reverse("process:main", kwargs={"process": "forming"}))
        self.assertContains(response, "Complete")
        self.assertContains(response, "View")

    def test_completed_transaction_is_not_offered_a_complete_action(self):
        self.seed_forming_wip("480")
        transaction = self.make_forming(input_qty="480", output_qty="460", rejection_qty="15")
        from apps.production import services as prod_services

        prod_services.complete_stage(transaction, self.admin, current_stage="forming")
        response = self.client.get(reverse("process:main", kwargs={"process": "forming"}))
        complete_url = reverse("forming:complete", kwargs={"pk": transaction.pk})
        self.assertNotContains(response, complete_url)

    def test_a_process_added_to_the_registry_gets_both_screens(self):
        """Adding a process must not require new views, routes or markup."""
        from apps.production import process_registry as registry

        class PackingProcess(registry.StageProcess):
            slug = "packing"
            stage = "packing"
            label = "Packing"
            icon = "bi-box"
            model_path = "forming.FormingTransaction"
            create_url_name = "forming:create"
            main_columns = (*registry.StageProcess.identity_columns, *registry.StageProcess.weight_columns)
            complete_columns = (
                *registry.StageProcess.identity_columns,
                registry.Column("Transaction #", "transaction_number"),
                *registry.StageProcess.weight_columns,
            )

        extra = PackingProcess()
        registry.PROCESSES.append(extra)
        registry.PROCESS_BY_SLUG["packing"] = extra
        try:
            for submenu in ("main", "complete"):
                response = self.client.get(reverse(f"process:{submenu}", kwargs={"process": "packing"}))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Packing")
        finally:
            registry.PROCESSES.remove(extra)
            registry.PROCESS_BY_SLUG.pop("packing")


class ProcessMenuTests(WorkflowTestBase):
    """The sidebar is generated from the registry, and highlights the
    active process + submenu server-side so refreshes are correct."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_menu_lists_every_process_with_both_submenus(self):
        response = self.client.get(reverse("process:main", kwargs={"process": "rolling"}))
        body = response.content.decode()
        for process in PROCESSES:
            self.assertIn(f'data-process="{process.slug}"', body)
            self.assertIn(reverse("process:main", kwargs={"process": process.slug}), body)
            self.assertIn(reverse("process:complete", kwargs={"process": process.slug}), body)

    def test_active_submenu_is_marked_on_the_complete_table(self):
        response = self.client.get(reverse("process:complete", kwargs={"process": "finishing"}))
        nav = response.context["process_nav"]
        finishing = next(group for group in nav if group["slug"] == "finishing")
        self.assertTrue(finishing["is_active"])
        self.assertTrue(next(s for s in finishing["submenus"] if s["key"] == "complete")["is_active"])
        self.assertFalse(next(s for s in finishing["submenus"] if s["key"] == "main")["is_active"])

    def test_drilldown_screen_highlights_the_main_table_branch(self):
        self.seed_forming_wip("480")
        transaction = self.make_forming()
        response = self.client.get(reverse("forming:detail", kwargs={"pk": transaction.pk}))
        forming = next(g for g in response.context["process_nav"] if g["slug"] == "forming")
        self.assertTrue(forming["is_active"])
        self.assertTrue(next(s for s in forming["submenus"] if s["key"] == "main")["is_active"])
