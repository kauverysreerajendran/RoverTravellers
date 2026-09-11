"""Load the real Diameter <-> Traveller Type mappings from a CSV.

There is no screen for `DiameterTravellerMapping`, and only one row is
confirmed, so `seed_process_history` invents provisional mappings to get
the demo moving. This command is how those provisional rows are replaced
with the business's real values.

CSV columns: seq_no,diameter_mm,f_thickness_mm,f_width_mm
`seq_no` is the Traveller Type Master row number - the business key, since
the official list repeats a name at rows 17 and 63.
"""

import csv
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.masters.models import DiameterMaster, DiameterTravellerMapping, TravellerType

REQUIRED_COLUMNS = ["seq_no", "diameter_mm", "f_thickness_mm", "f_width_mm"]


class Command(BaseCommand):
    help = "Import Diameter/Traveller Type mappings from a CSV (seq_no,diameter_mm,f_thickness_mm,f_width_mm)."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="Path to the mapping CSV.")
        parser.add_argument(
            "--dry-run", action="store_true", help="Report what would change without writing anything."
        )

    def handle(self, *args, **options):
        rows = self._read(options["csv_path"])
        created = updated = 0
        errors = []

        with transaction.atomic():
            for line_no, row in rows:
                try:
                    traveller_type = TravellerType.objects.get(seq_no=int(row["seq_no"]))
                    diameter = DiameterMaster.objects.get(diameter_mm=Decimal(row["diameter_mm"]))
                    values = {
                        "raw_material": diameter,
                        "f_thickness_mm": Decimal(row["f_thickness_mm"]),
                        "f_width_mm": Decimal(row["f_width_mm"]),
                    }
                except TravellerType.DoesNotExist:
                    errors.append(f"line {line_no}: no traveller type with seq_no {row['seq_no']}")
                    continue
                except DiameterMaster.DoesNotExist:
                    errors.append(f"line {line_no}: no diameter {row['diameter_mm']} mm in the master")
                    continue
                except (InvalidOperation, ValueError) as exc:
                    errors.append(f"line {line_no}: {exc}")
                    continue

                _, was_created = DiameterTravellerMapping.objects.update_or_create(
                    traveller_type=traveller_type, defaults=values
                )
                created += was_created
                updated += not was_created

            if errors:
                raise CommandError("Nothing imported:\n  " + "\n  ".join(errors))
            if options["dry_run"]:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("Dry run - rolled back."))

        self.stdout.write(self.style.SUCCESS(f"Mappings imported: {created} created, {updated} updated."))

    def _read(self, path):
        try:
            with open(path, newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
                if missing:
                    raise CommandError(f"CSV is missing the column(s): {', '.join(missing)}")
                return list(enumerate(reader, start=2))
        except FileNotFoundError:
            raise CommandError(f"No such file: {path}")
