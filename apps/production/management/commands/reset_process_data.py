"""Wipe every process record while leaving master data untouched.

The line between the two is the point of this command: master data is
what the business maintains (traveller types, diameters, racks, machines,
users), process data is what the shop floor produces (batches, stage
transactions, lots, stock, the audit trail). Everything in the second
group is discovered from the process registry wherever possible, so a
sixth process added to `PROCESSES` is cleared without editing this file.
"""

from django.apps import apps as django_apps
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.masters.models import DiameterMaster, RackSlot, WireSerialMaster
from apps.production.process_registry import PROCESSES

# Never touched. Their row counts are asserted identical before and after.
PROTECTED_MODELS = [
    "masters.TravellerType",
    "masters.TravellerNo",
    "masters.SurfaceFinish",
    "masters.DiameterMaster",
    "masters.RackMaster",
    # The storage zones and their slots are master data - the grids exist
    # whether or not anything is sitting on them. What is sitting on them
    # is process data, cleared by vacating the slots below.
    "masters.RackZone",
    "masters.StorageRack",
    "masters.RackSlot",
    "masters.DiameterTravellerMapping",
    "masters.WireSerialMaster",
    "masters.Machine",
    "accounts.User",
    "accounts.Role",
    "accounts.UserRole",
]

# Child rows and ledgers that hang off the process records. Listed in
# dependency order: children before parents, so a PROTECT foreign key that
# this command does not know about surfaces as an error instead of being
# silently left behind. The process records themselves are spliced in
# between, read from the registry.
CHILD_MODELS = [
    "masters.RackPlacement",
    "rolling.RollingBatchCoil",
    "production.OperationQualityCheck",
    "production.OperationStatusHistory",
]

LEDGER_MODELS = [
    "inventory.StockTransaction",
    "inventory.StockTransfer",
    "inventory.StockAdjustment",
    "inventory.WIPStock",
    "inventory.RawMaterialStock",
]

TAIL_MODELS = [
    # Furnace loads are process data; they are deleted after the
    # transactions that point at them.
    "heat_treatment.HeatBatch",
    "production.ProductionLot",
    "production.ProductionOrder",
    "masters.CoilMaster",
    "audit.AuditLog",
]

# The wire serial the shop floor had reached when the masters were seeded.
DEFAULT_CURRENT_SERIAL = "SB110"


def _model(path):
    """Resolve "app.Model", or None if that model no longer exists - the
    optional tables in the lists above are allowed to have been removed."""
    try:
        return django_apps.get_model(path)
    except LookupError:
        return None


def deletion_plan():
    """Every model this command clears, in the order it clears them."""
    paths = list(CHILD_MODELS)
    # Finished Goods stock is both a process record and a stock table; the
    # registry supplies it, so it is not listed twice.
    paths += [f"{p.model._meta.app_label}.{p.model.__name__}" for p in PROCESSES]
    paths += LEDGER_MODELS + TAIL_MODELS

    seen, plan = set(), []
    for path in paths:
        model = _model(path)
        if model is None or model in seen:
            continue
        seen.add(model)
        plan.append((path, model))
    return plan


def protected_counts():
    counts = {}
    for path in PROTECTED_MODELS:
        model = _model(path)
        if model is not None:
            counts[path] = model.objects.count()
    return counts


class Command(BaseCommand):
    help = "Delete every process record (batches, transactions, lots, stock, audit) and leave master data untouched."

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes", action="store_true",
            help="Actually delete. Without it the command only prints what it would delete.",
        )
        parser.add_argument(
            "--current-serial", default=DEFAULT_CURRENT_SERIAL,
            help=f"Wire serial to rewind the master to (default {DEFAULT_CURRENT_SERIAL}). "
                 "Everything up to it stays Used; everything after becomes Available.",
        )

    def handle(self, *args, **options):
        plan = deletion_plan()
        before = protected_counts()

        if not options["yes"]:
            self.stdout.write(self.style.WARNING("Dry run - nothing deleted. Re-run with --yes to proceed.\n"))
            self._print_table("Would delete", [(path, model.objects.count()) for path, model in plan])
            self._print_table("Would keep (master data)", sorted(before.items()))
            raise CommandError("Refusing to delete without --yes.")

        with transaction.atomic():
            deleted = []
            for path, model in plan:
                count = model.objects.count()
                model.objects.all().delete()
                deleted.append((path, count))
            self._vacate_rack_slots()
            self._rewind_wire_serials(options["current_serial"])
            for diameter in DiameterMaster.objects.all():
                diameter.recalculate_stock()

        after = protected_counts()
        changed = {path: (before[path], after[path]) for path in before if before[path] != after[path]}
        if changed:
            raise CommandError(f"Master data was modified, which must never happen: {changed}")

        self._print_table("Deleted", deleted)
        self._print_table("Kept (master data, unchanged)", sorted(after.items()))
        self.stdout.write(self.style.SUCCESS("Process data cleared. Master data intact."))

    def _vacate_rack_slots(self):
        """Deleting the lots already empties `RackSlot.lot` (SET_NULL); this
        clears the rest of the occupancy so every slot reads as empty."""
        vacated = RackSlot.objects.exclude(
            lot__isnull=True, placed_at__isnull=True, placed_by__isnull=True
        ).update(lot=None, placed_at=None, placed_by=None)
        self.stdout.write(f"  Rack slots vacated: {vacated}")

    def _rewind_wire_serials(self, current_serial):
        """Put the wire serial master back to its seed baseline: used up to
        and including `current_serial`, available after it."""
        serial = WireSerialMaster.objects.filter(serial_no=current_serial).first()
        if serial is None:
            raise CommandError(f"Wire serial {current_serial} is not in the master.")
        WireSerialMaster.objects.filter(sort_order__lte=serial.sort_order).update(status="Used")
        WireSerialMaster.objects.filter(sort_order__gt=serial.sort_order).update(
            status="Available", used_at=None
        )
        available = WireSerialMaster.objects.filter(status="Available").order_by("sort_order").first()
        self.stdout.write(
            f"  Wire serials rewound to {current_serial}; next serial: "
            f"{available.serial_no if available else 'none left'}"
        )

    def _print_table(self, title, rows):
        width = max([len(path) for path, _ in rows] + [len(title)])
        self.stdout.write("")
        self.stdout.write(f"{title.ljust(width)}  rows")
        self.stdout.write(f"{'-' * width}  ----")
        for path, count in rows:
            self.stdout.write(f"{path.ljust(width)}  {count}")
