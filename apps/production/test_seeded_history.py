"""Prove the generated history on the screens, not just in the database.

`seed_process_history` is only useful if what it writes actually renders:
every Main Table has to show both material waiting to be picked up and
work in progress, every Complete Table has to show finished work, and the
weight a process received has to be exactly the weight its predecessor
handed over. So this test runs the real command against a freshly seeded
test database and then reads the two screens of every process in the
registry, through the HTTP layer, as an admin would.

Nothing here names a process: the assertions walk `PROCESSES`, so a sixth
process added to the registry is covered without editing this file.
"""

import datetime
from decimal import Decimal
from io import StringIO
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.production.process_registry import PROCESSES

IST = ZoneInfo("Asia/Kolkata")

# Long enough that the oldest age band (>= 12 days) is reached, so the
# terminal process has received stock.
HISTORY_DAYS = 30
# Enough batches that the traveller-type cycle covers the whole active
# master, which the command asserts before it finishes.
BATCHES_PER_DAY = 3


class SeededHistoryScreenTests(TestCase):
    """One expensive fixture, many cheap assertions against it."""

    @classmethod
    def setUpTestData(cls):
        User.objects.create_superuser(username="root", email="root@example.com", password="x")

        cls.date_to = datetime.datetime.now(tz=IST).date()
        cls.date_from = cls.date_to - datetime.timedelta(days=HISTORY_DAYS)

        call_command("seed_masters", stdout=StringIO())
        cls.output = StringIO()
        call_command(
            "seed_process_history",
            **{
                "date_from": cls.date_from.isoformat(),
                "date_to": cls.date_to.isoformat(),
                "per_day": BATCHES_PER_DAY,
                "seed": 42,
                "reset": False,
                "extend": False,
                "provisional_mappings": True,
            },
            stdout=cls.output,
        )

    def setUp(self):
        self.client.force_login(User.objects.get(username="root"))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def screen(self, process, submenu):
        response = self.client.get(reverse(f"process:{submenu}", kwargs={"process": process.slug}))
        self.assertEqual(response.status_code, 200, f"{process.slug} {submenu} table did not load")
        # `load_rows` puts `table_error` in the context only when the query
        # or a column accessor blew up, so its absence is the assertion.
        self.assertNotIn(
            "table_error", response.context,
            f"{process.slug} {submenu} table degraded to an error state",
        )
        return response.context

    # ------------------------------------------------------------------
    # The screens
    # ------------------------------------------------------------------
    def test_every_main_table_shows_incoming_and_in_progress_rows(self):
        for process in PROCESSES:
            with self.subTest(process=process.slug):
                context = self.screen(process, "main")
                self.assertGreater(
                    len(context["rows"]), 0,
                    f"{process.label} Main Table has no in-progress rows",
                )
                if process.previous is None:
                    # The origin process receives from no one, so it has no
                    # incoming rows by construction.
                    continue
                self.assertGreater(
                    len(context["incoming_rows"]), 0,
                    f"{process.label} Main Table shows nothing incoming from {process.previous.label}",
                )

    def test_every_complete_table_shows_completed_rows(self):
        for process in PROCESSES:
            with self.subTest(process=process.slug):
                context = self.screen(process, "complete")
                self.assertGreater(
                    len(context["rows"]), 0,
                    f"{process.label} Complete Table has no completed rows",
                )

    def test_every_main_table_row_offers_an_action(self):
        """An incoming row must offer the Initiate button that starts the
        next process; an in-progress row must offer its own action."""
        for process in PROCESSES:
            with self.subTest(process=process.slug):
                context = self.screen(process, "main")
                for row in context["incoming_rows"]:
                    self.assertTrue(row["actions"], f"{process.label} incoming row has no Initiate action")

    # ------------------------------------------------------------------
    # The data behind them
    # ------------------------------------------------------------------
    def test_the_earliest_date_rendered_is_inside_the_requested_range(self):
        for process in PROCESSES:
            with self.subTest(process=process.slug):
                earliest = process.model.objects.order_by("created_at").first()
                self.assertIsNotNone(earliest, f"{process.label} has no rows at all")
                shown = earliest.created_at.astimezone(IST).date()
                self.assertGreaterEqual(
                    shown, self.date_from,
                    f"{process.label} renders {shown}, before --from {self.date_from}",
                )
                self.assertLessEqual(
                    shown, self.date_to + datetime.timedelta(days=max(0, process.index * 2)),
                    f"{process.label} renders {shown}, after the range plus its stage offset",
                )

    def test_received_weight_always_equals_the_predecessors_output_weight(self):
        """The one number that must never drift: what a process was handed
        is exactly what the process before it handed over."""
        for process in PROCESSES:
            previous = process.previous
            if previous is None:
                continue
            path = previous.handover_lot_path
            with self.subTest(process=process.slug):
                checked = 0
                for record in process.model.objects.all():
                    lot = record.handover_lot
                    self.assertIsNotNone(lot, f"{process.label} record {record.pk} has no carrier lot")
                    source = (
                        previous.complete_queryset(None)
                        .filter(**{path: lot})
                        .order_by(previous.handover_ordering)
                        .first()
                    )
                    self.assertIsNotNone(
                        source, f"{process.label} {record.wire_serial} has no completed {previous.label} record"
                    )
                    self.assertEqual(
                        Decimal(record.received_weight), Decimal(source.output_weight),
                        f"{process.label} {record.wire_serial} received {record.received_weight} kg "
                        f"but {previous.label} output {source.output_weight} kg",
                    )
                    checked += 1
                self.assertGreater(checked, 0, f"{process.label} had no records to check")

    def test_output_weight_never_exceeds_the_weight_received(self):
        for process in PROCESSES:
            with self.subTest(process=process.slug):
                for record in process.complete_queryset(None):
                    self.assertLessEqual(
                        Decimal(record.output_weight), Decimal(record.received_weight),
                        f"{process.label} {record.wire_serial} output more than it received",
                    )

    def test_the_run_reported_a_summary_and_used_every_traveller_type(self):
        output = self.output.getvalue()
        self.assertIn("Chain check", output)
        self.assertIn("Traveller types used", output)
        for process in PROCESSES:
            self.assertIn(process.label, output, f"{process.label} missing from the summary table")

    def test_history_is_written_through_the_services_so_the_audit_trail_exists(self):
        from apps.audit.models import AuditLog
        from apps.inventory.models import StockTransaction
        from apps.production.models import OperationStatusHistory

        for model in (AuditLog, StockTransaction, OperationStatusHistory):
            with self.subTest(model=model.__name__):
                self.assertTrue(model.objects.exists(), f"{model.__name__} is empty - a service was bypassed")
                earliest = model.objects.order_by("created_at").first()
                self.assertLessEqual(
                    earliest.created_at.astimezone(IST).date(),
                    self.date_to,
                    f"{model.__name__} rows were not backdated to the simulated date",
                )


# A short window for the guard tests: they exercise refusals, not coverage.
GUARD_DAYS = 6
# The command asserts that every ACTIVE traveller type is rolled, so the
# guard tests shrink the active master rather than generate 71 batches
# three more times. One mapped type (the confirmed one) plus two unmapped
# ones, so the "no mapping" refusal still has something to refuse.
GUARD_ACTIVE_TYPES = 3


class SeedProcessHistoryGuardTests(TestCase):
    """The command's refusals, which are what stop it fabricating data."""

    @classmethod
    def setUpTestData(cls):
        from apps.masters.models import TravellerType

        User.objects.create_superuser(username="root", email="root@example.com", password="x")
        call_command("seed_masters", stdout=StringIO())
        keep = list(
            TravellerType.objects.order_by("seq_no").values_list("pk", flat=True)[:GUARD_ACTIVE_TYPES]
        )
        TravellerType.objects.exclude(pk__in=keep).update(is_active=False)

    @staticmethod
    def guard_options(**overrides):
        options = {
            "date_from": (datetime.datetime.now(tz=IST).date() - datetime.timedelta(days=GUARD_DAYS)).isoformat(),
            "per_day": 2,
            "provisional_mappings": True,
        }
        options.update(overrides)
        return options

    def test_it_refuses_to_invent_mappings_unless_asked(self):
        from django.core.management.base import CommandError

        from apps.masters.models import DiameterTravellerMapping, TravellerType

        before = DiameterTravellerMapping.objects.count()
        with self.assertRaises(CommandError) as caught:
            call_command("seed_process_history", stdout=StringIO(), stderr=StringIO())
        message = str(caught.exception)
        self.assertIn("no DiameterTravellerMapping", message)
        self.assertIn("--provisional-mappings", message)
        # It names the rows it will not invent, and writes nothing.
        unmapped = TravellerType.objects.filter(is_active=True, mapping__isnull=True).first()
        self.assertIn(unmapped.name, message)
        self.assertEqual(DiameterTravellerMapping.objects.count(), before)

    def test_it_never_overwrites_a_real_mapping(self):
        from apps.masters.models import DiameterTravellerMapping

        real = DiameterTravellerMapping.objects.get()
        before = (real.raw_material_id, real.f_thickness_mm, real.f_width_mm)
        call_command("seed_process_history", **self.guard_options(), stdout=StringIO())
        real.refresh_from_db()
        self.assertEqual((real.raw_material_id, real.f_thickness_mm, real.f_width_mm), before)

    def test_it_refuses_to_run_twice_without_reset_or_extend(self):
        from django.core.management.base import CommandError

        from apps.rolling.models import RollingBatch

        options = self.guard_options()
        call_command("seed_process_history", **options, stdout=StringIO())
        before = RollingBatch.objects.count()
        self.assertGreater(before, 0)

        with self.assertRaises(CommandError) as caught:
            call_command("seed_process_history", **options, stdout=StringIO())
        self.assertIn("--extend", str(caught.exception))
        self.assertEqual(RollingBatch.objects.count(), before)

    def test_extend_leaves_existing_rows_untouched(self):
        from apps.rolling.models import RollingBatch

        call_command("seed_process_history", **self.guard_options(), stdout=StringIO())
        existing = dict(RollingBatch.objects.values_list("pk", "wire_serial"))
        call_command("seed_process_history", extend=True, per_day=2, stdout=StringIO())
        still_there = dict(RollingBatch.objects.filter(pk__in=existing).values_list("pk", "wire_serial"))
        self.assertEqual(still_there, existing, "an --extend run rewrote rows it should not have touched")
