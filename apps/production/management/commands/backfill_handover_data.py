"""Bring a database that predates the handover chain up to date.

Two things changed that a schema migration cannot fix on its own, and
migrations are not tracked in this repo (see .gitignore), so this command
is the portable way to apply them:

1. A Rolling batch's carrier ProductionLot used to be created when the
   batch was *completed*. It is now created when the batch is *initiated*,
   so the lot the next process initiates against exists for the whole life
   of the batch. A batch that was already In Progress has no lot to hand
   over and could never be completed.

2. `completed_at` did not exist on the stage transactions. Records
   completed before it was added carry NULL, which sorts apart from
   everything else in the next process's incoming rows.

Safe to run more than once: it only touches rows that are still missing
these values, and reports what it changed.

    python manage.py backfill_handover_data --dry-run
    python manage.py backfill_handover_data
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F

from apps.production.process_registry import PROCESSES
from apps.rolling.models import RollingBatch


class Command(BaseCommand):
    help = "Backfill carrier lots and completed_at on a database created before the handover chain."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="Report what would change without writing anything."
        )

    def handle(self, *args, **options):
        with transaction.atomic():
            lots = self._backfill_carrier_lots(options["dry_run"])
            stamps = self._backfill_completed_at(options["dry_run"])
            if options["dry_run"]:
                transaction.set_rollback(True)

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run - nothing written."))
        if not lots and not stamps:
            self.stdout.write(self.style.SUCCESS("Nothing to backfill; this database is already up to date."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Carrier lots: {lots}. Completion stamps: {stamps}."))

    # ------------------------------------------------------------------
    def _backfill_carrier_lots(self, dry_run):
        from apps.rolling.services import _create_carrier_lot

        origin, following = PROCESSES[0], PROCESSES[0].next
        orphans = list(RollingBatch.objects.filter(production_lots__isnull=True).order_by("created_at"))
        for batch in orphans:
            self.stdout.write(f"  {batch.wire_serial}: no carrier lot ({batch.status})")
            if dry_run:
                continue
            lot = _create_carrier_lot(batch)
            if batch.status == origin.completed_status:
                # Already handed over: the lot belongs at the next process,
                # carrying what Rolling actually produced.
                lot.current_stage = following.slug if following else origin.slug
                lot.quantity = batch.finished_weight_kg or batch.wire_weight_issued_kg
                lot.save(update_fields=["current_stage", "quantity", "updated_at"])
        return len(orphans)

    def _backfill_completed_at(self, dry_run):
        stamped = 0
        for process in PROCESSES:
            model = process.model
            columns = {field.name for field in model._meta.concrete_fields}
            # Rolling has always stamped its own completion time, and the
            # terminal process serves completed_at as a property.
            if "completed_at" not in columns or "updated_at" not in columns:
                continue
            missing = model.objects.filter(
                **{process.status_field: process.completed_status}, completed_at__isnull=True
            )
            count = missing.count()
            if count:
                self.stdout.write(f"  {process.label}: {count} completed record(s) with no completion time")
                if not dry_run:
                    missing.update(completed_at=F("updated_at"))
            stamped += count
        return stamped
