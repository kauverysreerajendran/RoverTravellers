"""Regression tests for the configuration-driven process screens.

These cover the contract the registry promises: every registered process
gets a working Main Table and Complete Table, Wire Serial is always
shown, Lot never is, and the two tables are genuinely different screens.
"""

from decimal import Decimal

from django import forms
from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from apps.inventory import services as inv_services
from apps.inventory.models import WIPStock
from apps.masters import services as masters_services
from apps.masters.models import (
    DiameterMaster, DiameterTravellerMapping, RackMaster, WireSerialMaster,
)
from apps.production import services as prod_services
from apps.production.process_registry import PROCESSES, get_process
from apps.production.tests import WorkflowTestBase
from apps.rolling import services as rolling_services


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
        """The weight a process is handed reads "Received Weight"; its own
        result reads "Output Weight". Rolling, the origin process, receives
        nothing and so carries no Received Weight column at all."""
        for process in PROCESSES:
            for name in ("main_columns", "complete_columns"):
                labels = [c.label for c in getattr(process, name)]
                with self.subTest(process=process.slug, table=name):
                    self.assertNotIn("Weight Received", labels)
                    self.assertEqual(
                        len([lbl for lbl in labels if lbl.startswith("Received Weight")]),
                        0 if process.previous is None else 1,
                    )
                    self.assertEqual([lbl for lbl in labels if "Finished Weight" in lbl], [])

    def test_the_phrase_finished_weight_is_gone_from_the_codebase(self):
        """The rename is the contract: one name for the weight a process
        receives, everywhere it is written down."""
        import os

        roots = [
            os.path.join(settings.BASE_DIR, "apps"),
            os.path.join(settings.BASE_DIR, "static", "templates"),
        ]
        offenders = []
        for root in roots:
            for dirpath, dirnames, filenames in os.walk(root):
                if "migrations" in dirpath or "__pycache__" in dirpath:
                    continue
                for filename in filenames:
                    if not filename.endswith((".py", ".html")) or filename.startswith("test_"):
                        continue
                    path = os.path.join(dirpath, filename)
                    with open(path, encoding="utf-8") as handle:
                        if "Finished Weight" in handle.read():
                            offenders.append(os.path.relpath(path, settings.BASE_DIR))
        self.assertEqual(offenders, [], "'Finished Weight' must read 'Received Weight'")

    def test_no_module_decides_the_pipeline_order_for_itself(self):
        """Process order lives in PROCESSES. Nothing may reintroduce a
        hardcoded next/previous stage map or a stage-slug lot filter."""
        import os
        import re

        banned = ("NEXT_WIP_STAGE", "STEPPER_STAGES", "pending_lots_for_stage")
        slug_filter = re.compile(r'current_stage="(' + "|".join(p.slug for p in PROCESSES) + r')"')
        offenders = []
        for dirpath, dirnames, filenames in os.walk(os.path.join(settings.BASE_DIR, "apps")):
            if "migrations" in dirpath or "__pycache__" in dirpath:
                continue
            for filename in filenames:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(dirpath, filename)
                with open(path, encoding="utf-8") as handle:
                    body = handle.read()
                rel = os.path.relpath(path, settings.BASE_DIR)
                if os.path.basename(path).startswith("test_"):
                    continue
                for symbol in banned:
                    if symbol in body:
                        offenders.append(f"{rel}: {symbol}")
                match = slug_filter.search(body)
                if match:
                    offenders.append(f"{rel}: {match.group(0)}")
        self.assertEqual(offenders, [])

    # Columns retired from the process screens. Nothing may reintroduce them.
    RETIRED_LABELS = {
        "lot no", "operator", "time out", "timeout", "transaction #", "completion",
        "created", "created by", "completed", "shift", "rejection (kg)", "rejected (kg)",
        "traveller date", "tt", "t no", "date out", "product", "fg batch #", "qc approved", "approved by",
    }
    RETIRED_ACCESSORS = (
        "operator", "time_out", "rejection_quantity", "rejected_quantity", "shift", "created_at", "created_by",
        "traveller_date", "date_out", "quality_approved", "fg_lot_number", "product.",
    )

    def test_retired_columns_stay_out_of_every_table(self):
        for process in PROCESSES:
            for name in ("main_columns", "complete_columns"):
                for column in getattr(process, name):
                    with self.subTest(process=process.slug, column=column.label):
                        self.assertNotIn(column.label.lower(), self.RETIRED_LABELS)
                        for accessor in self.RETIRED_ACCESSORS:
                            self.assertNotIn(accessor, column.accessor)
                            self.assertNotIn(accessor, column.pending)
                        self.assertNotEqual(column.kind, "completion")

    def test_heat_treatment_drops_its_machine_and_furnace_columns(self):
        """Heat Treatment shows no Machine, HT Type, Temperature or Holding
        Time - unlike Forming and Finishing, which keep their Machine column."""
        labels = [c.label for c in get_process("heat_treatment").complete_columns]
        for gone in ("Machine", "HT Type", "Temperature (C)", "Holding Time (min)"):
            self.assertNotIn(gone, labels)
        for slug in ("forming", "finishing"):
            self.assertIn("Machine", [c.label for c in get_process(slug).complete_columns])

    def test_traveller_type_is_present_in_every_table(self):
        """Traveller Type is required on every process screen, the same way
        Wire Serial is - downstream stages read it through the lot."""
        for process in PROCESSES:
            for name in ("main_columns", "complete_columns"):
                labels = [column.label for column in getattr(process, name)]
                with self.subTest(process=process.slug, table=name):
                    self.assertIn("Traveller Type", labels)

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

    def test_heat_treatment_initiates_without_a_machine(self):
        """Heat Treatment records no machine at all, so its Initiate form
        must neither offer the field nor require one to initiate."""
        from apps.heat_treatment.forms import HeatTreatmentInitiateForm

        self.assertNotIn("machine", HeatTreatmentInitiateForm().fields)

        self.seed_forming_wip("480")
        forming = self.make_forming(input_qty="480", output_qty="460", rejection_qty="15")
        prod_services.complete_stage(forming, self.admin)

        record = prod_services.initiate_stage(
            get_process("heat_treatment"), self.lot, self.admin,
            batch_number="B1", operation_date="2026-01-01",
        )
        self.assertIsNone(record.machine)
        self.assertEqual(record.input_quantity, Decimal("460.000"))

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
        """The transaction number is still searchable even though it is no
        longer a visible column, so matches are counted, not read off."""
        self.seed_forming_wip("480")
        transaction = self.make_forming(input_qty="480", output_qty="460", rejection_qty="15")
        prod_services.complete_stage(transaction, self.admin)
        url = reverse("process:complete", kwargs={"process": "forming"})

        hit = self.client.get(url, {"q": transaction.transaction_number})
        self.assertEqual(hit.context["page_obj"].paginator.count, 1)

        miss = self.client.get(url, {"q": "NO-SUCH-RECORD"})
        self.assertEqual(miss.context["page_obj"].paginator.count, 0)
        self.assertContains(miss, "No records match this filter")

    def test_empty_process_shows_its_empty_state(self):
        complete = self.client.get(reverse("process:complete", kwargs={"process": "finishing"}))
        self.assertContains(complete, "No completed finishing records yet")

        main = self.client.get(reverse("process:main", kwargs={"process": "finishing"}))
        self.assertContains(main, "Nothing in progress at Finishing")

    def test_incoming_row_shows_the_weight_the_previous_process_handed_over(self):
        """The incoming Main Table row reads its Received Weight from the
        predecessor record's Output Weight, not the lot's original quantity
        (which never shrinks as material moves down the line)."""
        self.seed_forming_wip("480")
        forming = self.make_forming(input_qty="480", output_qty="123.456", rejection_qty="15")
        prod_services.complete_stage(forming, self.admin)

        response = self.client.get(reverse("process:main", kwargs={"process": "heat_treatment"}))
        self.assertContains(response, "123.456")
        self.assertNotContains(response, str(self.lot.quantity))
        self.assertContains(response, "Initiate")
        # The WIP ledger is a guard behind the screen, and agrees with it.
        self.assertEqual(
            inv_services.WIPStock.objects.get(stage="heat_treatment", lot=self.lot).quantity,
            Decimal("123.456"),
        )

    def test_completed_work_leaves_the_main_table_for_the_complete_table(self):
        """Main Table = yet to start + in progress. Once a record is
        completed it belongs to the Complete Table (and the next stage)."""
        self.seed_forming_wip("480")
        transaction = self.make_forming(input_qty="480", output_qty="460", rejection_qty="15")

        main = reverse("process:main", kwargs={"process": "forming"})
        complete = reverse("process:complete", kwargs={"process": "forming"})
        # Neither table shows a transaction number any more, so rows are
        # counted rather than matched on text.
        row_marker = reverse("forming:complete", kwargs={"pk": transaction.pk})

        # While in progress: on the Main Table, not on the Complete Table.
        self.assertContains(self.client.get(main), row_marker)
        self.assertEqual(self.client.get(complete).context["page_obj"].paginator.count, 0)

        prod_services.complete_stage(transaction, self.admin)

        # Once completed: gone from Main, present on Complete.
        self.assertNotContains(self.client.get(main), row_marker)
        self.assertEqual(self.client.get(complete).context["page_obj"].paginator.count, 1)

    def test_completed_work_appears_on_the_next_stage_main_table(self):
        self.seed_forming_wip("480")
        transaction = self.make_forming(input_qty="480", output_qty="460", rejection_qty="15")
        prod_services.complete_stage(transaction, self.admin)

        response = self.client.get(reverse("process:main", kwargs={"process": "heat_treatment"}))
        self.assertContains(response, self.lot.wire_serial)
        self.assertContains(response, "Initiate")
        self.assertContains(response, "460")  # the weight Forming handed over

    def test_status_filter_only_offers_statuses_that_table_can_hold(self):
        main = self.client.get(reverse("process:main", kwargs={"process": "forming"}))
        complete = self.client.get(reverse("process:complete", kwargs={"process": "forming"}))
        main_codes = [code for code, _ in main.context["status_choices"]]
        complete_codes = [code for code, _ in complete.context["status_choices"]]
        # The Main Table also holds rows that are not Forming records at
        # all, so it offers the virtual "incoming" filter alongside them.
        self.assertEqual(sorted(main_codes), ["draft", "in_progress", "incoming"])
        self.assertNotIn("in_progress", complete_codes)
        self.assertNotIn("incoming", complete_codes)
        self.assertIn("completed", complete_codes)

        # Rolling has no predecessor, so nothing can be incoming to it.
        rolling = self.client.get(reverse("process:main", kwargs={"process": "rolling"}))
        self.assertNotIn("incoming", [code for code, _ in rolling.context["status_choices"]])

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

        prod_services.complete_stage(transaction, self.admin)
        response = self.client.get(reverse("process:main", kwargs={"process": "forming"}))
        complete_url = reverse("forming:complete", kwargs={"pk": transaction.pk})
        self.assertNotContains(response, complete_url)

    def test_a_process_added_to_the_registry_gets_both_screens(self):
        """Adding a process must not require new views, routes or markup."""
        from apps.production import process_registry as registry

        class PackingProcess(registry.StageProcess):
            slug = "packing"
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
        last_real_process = registry.PROCESSES[-1]
        registry.PROCESSES.append(extra)
        registry.PROCESS_BY_SLUG["packing"] = extra
        try:
            for submenu in ("main", "complete"):
                response = self.client.get(reverse(f"process:{submenu}", kwargs={"process": "packing"}))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Packing")

            # Neighbours are read off the list, so the new process is the
            # successor of the last real one and receives its incoming rows.
            self.assertIs(last_real_process.next, extra)
            self.assertIs(extra.previous, last_real_process)
            self.assertIsNotNone(extra.incoming_queryset(None))
            self.assertEqual(
                extra.incoming_status_cell()["value"], f"Incoming from {last_real_process.label}"
            )
            main = self.client.get(reverse("process:main", kwargs={"process": "packing"}))
            self.assertIn("incoming", [code for code, _ in main.context["status_choices"]])
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


class ProcessChainTests(WorkflowTestBase):
    """The chain rule: every record on process N's Complete Table shows up
    on process N+1's Main Table as an incoming row until N+1 has been
    initiated for it.

    The test walks the registry pair by pair. It names no process slug: it
    asks each process for its neighbours, its services and its screens, so
    adding a sixth process to PROCESSES puts it under test automatically.
    """

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

        # The base fixture's batch stands in for history; park it as open
        # work so the only material moving through the chain is this test's.
        self.rolling_batch.status = "In Progress"
        self.rolling_batch.save(update_fields=["status"])

        self.diameter = DiameterMaster.objects.create(raw_material_id="RM-093", diameter_mm=Decimal("0.93"))
        DiameterTravellerMapping.objects.create(
            traveller_type=self.rolling_batch.traveller_type, raw_material=self.diameter,
            f_thickness_mm=Decimal("0.41"), f_width_mm=Decimal("1.78"),
        )
        WireSerialMaster.objects.create(
            serial_no="SB111", prefix="SB", sequence=111, sort_order=1111, status="Available"
        )
        rack = RackMaster.objects.create(rack_code="R1")
        self.coil = masters_services.receive_coil(
            raw_material=self.diameter, weight_kg=Decimal("500.00"), rack=rack
        )

    # ------------------------------------------------------------------
    # Generic helpers - these know the registry, not the processes
    # ------------------------------------------------------------------
    def start_at_origin(self):
        """Initiate a batch at the first process, through its own service."""
        return rolling_services.initiate_rolling_batch(
            traveller_type=self.rolling_batch.traveller_type,
            traveller_no=self.rolling_batch.traveller_no,
            finish=self.rolling_batch.finish,
            required_box=1,
            wire_weight_issued_kg=Decimal("400.00"),
            coil_weights=[(self.coil.coil_id, Decimal("400.00"))],
            user=self.admin,
        )

    def complete_record(self, record, output):
        """Complete `record` through the service its own screens call. The
        origin process issues wire from coils rather than receiving a lot,
        so it has its own completion service; every other process shares
        the generic one."""
        if hasattr(record, "wire_weight_issued_kg"):
            return rolling_services.complete_rolling_batch(
                record, rolled_thickness_mm=Decimal("0.41"), rolled_width_mm=Decimal("1.78"),
                finished_weight_kg=output, user=self.admin,
            )
        record.output_quantity = output
        record.save(update_fields=["output_quantity"])
        return prod_services.complete_stage(record, self.admin)

    def payload_for(self, form, lot, received):
        """Fill an Initiate/Receive form generically, from its field types."""
        data = {}
        for name, field in form.fields.items():
            if name == "lot":
                data[name] = str(lot.pk)
            elif isinstance(field, forms.ModelChoiceField):
                choice = field.queryset.first()
                if choice is not None:
                    data[name] = str(choice.pk)
            elif isinstance(field, forms.DecimalField):
                data[name] = "0" if "reject" in name else str(received)
            elif isinstance(field, forms.DateField):
                data[name] = "2026-04-01"
            else:
                data[name] = "T1"
        return data

    def initiate_via_screen(self, process, lot, received):
        """Initiate at `process` the way an operator does: follow the
        incoming row's button, then post its form."""
        url = f"{reverse(process.create_url_name)}?lot={lot.pk}"
        form = self.client.get(url).context["form"]
        response = self.client.post(url, self.payload_for(form, lot, received))
        self.assertIn(response.status_code, (200, 302))
        record = process.model.objects.filter(lot=lot).order_by("-created_at").first()
        self.assertIsNotNone(record, f"Initiating at {process.label} created no record")
        return record

    # ------------------------------------------------------------------
    def test_every_consecutive_pair_hands_material_over(self):
        record = self.start_at_origin()
        output = Decimal("400.00")

        for process, following in zip(PROCESSES, PROCESSES[1:]):
            with self.subTest(handover=f"{process.slug} -> {following.slug}"):
                output = (output - Decimal("10.00")).quantize(Decimal("0.01"))
                record = self.complete_record(record, output)
                record.refresh_from_db()
                lot = record.handover_lot
                handed_over = record.output_weight
                wire_serial = record.wire_serial

                # 1. It is on this process's Complete Table.
                complete = self.client.get(reverse("process:complete", kwargs={"process": process.slug}))
                self.assertContains(complete, wire_serial)

                # 2. It is an incoming row on the next process's Main Table,
                #    carrying the weight this process actually produced.
                main_url = reverse("process:main", kwargs={"process": following.slug})
                main = self.client.get(main_url)
                self.assertContains(main, wire_serial)
                self.assertContains(main, str(handed_over))
                self.assertContains(main, f"Incoming from {process.label}")
                self.assertContains(main, f"{reverse(following.create_url_name)}?lot={lot.pk}")
                self.assertIn(lot.pk, [r.handover_lot.pk for r in following.incoming_queryset(None)])

                # 3. The WIP ledger agrees with the number on the screen.
                self.assertEqual(
                    WIPStock.objects.get(stage=following.slug, lot=lot, status="available").quantity,
                    handed_over,
                )

                # 4. A search narrows the incoming rows rather than hiding
                #    them, and the virtual status filter selects them.
                self.assertContains(self.client.get(main_url, {"q": wire_serial}), wire_serial)
                self.assertContains(self.client.get(main_url, {"status": "incoming"}), wire_serial)
                hidden = self.client.get(main_url, {"status": list(following.open_statuses)[-1]})
                self.assertNotContains(hidden, f"Incoming from {process.label}")

                # 5. Once initiated there, it leaves the incoming list and
                #    shows as this process's own open row, at that weight.
                record = self.initiate_via_screen(following, lot, handed_over)
                self.assertEqual(record.received_weight, handed_over)
                self.assertNotIn(
                    lot.pk, [r.handover_lot.pk for r in following.incoming_queryset(None)]
                )
                after = self.client.get(main_url)
                self.assertNotContains(after, f"Incoming from {process.label}")
                self.assertContains(after, wire_serial)
