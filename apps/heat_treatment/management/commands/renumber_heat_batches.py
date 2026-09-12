"""Renumber heat batches into the B-series the business uses.

Batches carried over from before the batch grouping existed are numbered
the way the old per-transaction field was written (HT-2609-015). This
walks every batch in the order it was created and gives it the next number
in the active `masters.BatchNoFormat` series - B001, B002, ... - so the
shop floor reads one numbering everywhere.

The format is read from master data, so changing the pattern there and
running this again renumbers into the new shape. Each transaction's legacy
`batch_number` column is kept in step, because the reports and the search
still read it.

    python manage.py renumber_heat_batches --dry-run
    python manage.py renumber_heat_batches
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Min

from apps.heat_treatment.models import HeatBatch, HeatTreatmentTransaction
from apps.masters.models import BatchNoFormat


class Command(BaseCommand):
    help = "Renumber every heat batch into the active B-series format, oldest first."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Print the mapping and write nothing.")
        parser.add_argument(
            "--only-legacy", action="store_true",
            help="Leave batches that already match the format alone (renumbers only the rest, "
                 "appending them after the highest number in use).",
        )

    def handle(self, *args, **options):
        fmt = BatchNoFormat.for_process(HeatBatch.process())
        if fmt is None:
            raise CommandError("No batch number format is configured for Heat Treatment. Run seed_masters first.")

        # Ordered by when the work actually happened, not when the row was
        # written: the batches carried over from the old per-transaction
        # field were all created in one migration, so their own created_at
        # says nothing about the order the furnace ran in.
        batches = list(
            HeatBatch.objects.annotate(worked_at=Min("transactions__created_at"))
            .order_by("worked_at", "created_at", "pk")
        )
        if not batches:
            self.stdout.write("No heat batches to renumber.")
            return

        if options["only_legacy"]:
            keep = [b for b in batches if fmt.matches(b.batch_no)]
            renumber = [b for b in batches if not fmt.matches(b.batch_no)]
            start = max((fmt.number_of(b.batch_no) or 0) for b in keep) + 1 if keep else 1
        else:
            keep, renumber, start = [], batches, 1

        plan = []
        for offset, batch in enumerate(renumber):
            new_no = fmt.format_number(start + offset)
            if new_no != batch.batch_no:
                plan.append((batch, new_no))

        self.stdout.write(
            f"{len(batches)} batches | {len(keep)} already in format | {len(plan)} to renumber"
        )
        for batch, new_no in plan[:5]:
            self.stdout.write(f"   {batch.batch_no:<14} -> {new_no}")
        if len(plan) > 5:
            first, last = plan[0], plan[-1]
            self.stdout.write(
                f"   ... {len(plan) - 5} more, through {last[0].batch_no} -> {last[1]}"
            )

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run - nothing written."))
            return
        if not plan:
            self.stdout.write(self.style.SUCCESS("Every batch already carries its series number."))
            return

        with transaction.atomic():
            # Two passes, because the numbers being handed out are numbers
            # other batches are still holding: everything moves to a
            # scratch name first, so the unique constraint is never hit.
            for batch, _ in plan:
                HeatBatch.objects.filter(pk=batch.pk).update(batch_no=f"~{batch.pk}")
            for batch, new_no in plan:
                HeatBatch.objects.filter(pk=batch.pk).update(batch_no=new_no)
                HeatTreatmentTransaction.objects.filter(heat_batch=batch).update(batch_number=new_no)

        self.stdout.write(self.style.SUCCESS(
            f"Renumbered {len(plan)} batches; the series now runs "
            f"{fmt.format_number(start)} to {fmt.format_number(start + len(renumber) - 1)}. "
            f"Next free: {HeatBatch.objects.next_batch_no()}"
        ))
