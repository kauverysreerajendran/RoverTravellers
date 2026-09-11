"""Generate a realistic process history, through the real services.

Every record this command creates goes through exactly the service
functions the screens call - `initiate_rolling_batch`,
`complete_rolling_batch`, `production.services.initiate_stage`,
`complete_stage`/`handover`, `receive_finished_goods`,
`masters.services.receive_coil` - so a successful run is itself proof
that the whole pipeline works. No transaction, WIP or audit row is ever
inserted with `Model.objects.create()`; the only direct writes are the
timestamp backdating at the end of each step, which `auto_now_add` makes
impossible to do any other way.

Two rules keep the generated history honest:

*Master data is read, never invented.* Traveller types, traveller
numbers, surface finishes, diameters, the diameter/traveller mapping,
racks, machines and wire serials all come out of the master tables at run
time. No traveller-type name, diameter, serial prefix, machine code or
process slug is written here as a literal. If a master a step needs is
empty, the command names the missing row and stops before writing
anything, rather than making one up. The single exception is the known
gap - traveller types with no `DiameterTravellerMapping` - and even that
requires `--provisional-mappings` to be passed explicitly, prints every
invented row, and never overwrites a real mapping.

*Pipeline order is read from the registry.* The command walks `PROCESSES`
and uses `process.previous`/`process.next`, so a sixth process added to
the registry is generated, backdated and asserted without touching this
file.

Usage:
    python manage.py seed_masters
    python manage.py seed_process_history --reset --from 2026-04-01 --provisional-mappings
    python manage.py seed_process_history --extend        # daily top-up
"""

import datetime
import random
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max, Min
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.finished_goods import services as fg_services
from apps.inventory import services as inventory_services
from apps.inventory.models import FinishedGoodsStock, StockTransaction, WIPStock
from apps.masters import services as masters_services
from apps.masters.models import (
    CoilMaster,
    DiameterMaster,
    DiameterTravellerMapping,
    Machine,
    RackMaster,
    SurfaceFinish,
    TravellerNo,
    TravellerType,
    WireSerialMaster,
)
from apps.production import services as production_services
from apps.production.models import OperationStatusHistory
from apps.production.process_registry import PROCESSES
from apps.rolling import services as rolling_services
from apps.rolling.models import RollingBatch

IST = ZoneInfo("Asia/Kolkata")
DEFAULT_FROM = datetime.date(2026, 4, 1)

# Saturday is a working day; Sunday is not. `date.weekday()` numbers
# Monday 0 ... Sunday 6.
SUNDAY = 6

SUPPLIERS = [
    "Bharat Steel Suppliers",
    "Sundaram Wire Industries",
    "Kalyani Special Steels",
    "Tata Wiron",
]
COLOURS = ["Natural", "Blue", "Black", "Gold"]

# Provisional mapping formula, applied only to traveller types that have
# no real mapping. Replace with `import_traveller_mappings <csv>`.
THICKNESS_RATIO = Decimal("0.44")
WIDTH_RATIO = Decimal("1.90")

# Yield: each process hands on a little less than it received.
YIELD_RANGE = (0.960, 0.995)

# Coil receipts. Racks are read from RackMaster; these only describe the
# shape of a receipt, not any master value.
COILS_PER_DIAMETER = (3, 6)
COIL_WEIGHT_RANGE = (Decimal("40.00"), Decimal("95.00"))
# Coils land on the shelf before the history starts, so the first batch
# has stock to draw on.
COIL_LEAD_DAYS = 14

# One batch issues one to three draws of this size from stock.
DRAWS_PER_BATCH = (1, 3)
DRAW_WEIGHT_RANGE = (Decimal("10.00"), Decimal("45.00"))

REQUIRED_BOX_RANGE = (1, 6)
TRAVELLER_LENGTH_RANGE = (Decimal("400"), Decimal("900"))

# Working hours in IST. Initiation runs in the first window so that the
# completion two hours later still lands inside the day.
INITIATE_HOURS = (8, 15)
COMPLETE_OFFSET = datetime.timedelta(hours=2)

# How many days after a batch starts each process records its operation:
# Rolling +0, Forming +2, Heat Treatment +4, Finishing +6, FG +8.
DAY_OFFSET_PER_PROCESS = [0, 2, 4, 6, 8]

# How far a batch has got, by how old it is in days. The target is an
# index into PROCESSES, so the bands describe "reached process N" rather
# than naming a stage.
AGE_BANDS = [
    (12, 4, True),   # >= 12 days old: received at the last process
    (9, 3, True),    # 9-11: completed the second-to-last, incoming at the last
    (6, 2, True),
    (4, 1, True),
    (2, 0, True),
    (0, 0, False),   # 0-1 days: still in progress at the origin process
]

# One batch in every five is left initiated-but-not-completed at whatever
# process its age band reached, so every Main Table shows in-progress rows
# as well as incoming ones.
LEAVE_OPEN_EVERY = 5

# Models whose rows a service writes with `auto_now_add`, and which
# therefore have to be moved back to the simulated date afterwards.
BACKDATED_LEDGERS = (AuditLog, OperationStatusHistory, StockTransaction, WIPStock, FinishedGoodsStock)


def money(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class Command(BaseCommand):
    help = "Generate realistic process history from --from to --to, through the real service layer."

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="date_from", default=DEFAULT_FROM.isoformat())
        parser.add_argument("--to", dest="date_to", default="", help="Default: today in Asia/Kolkata.")
        parser.add_argument("--per-day", type=int, default=2, help="Batches started per working day (Mon-Sat).")
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--reset", action="store_true", help="Run reset_process_data --yes first.")
        parser.add_argument(
            "--extend", action="store_true",
            help="Only generate dates after the newest existing batch, leaving existing rows untouched.",
        )
        parser.add_argument(
            "--provisional-mappings", action="store_true", dest="provisional_mappings",
            help="Invent a mapping for traveller types that have none. Without this the command "
                 "lists them and exits rather than fabricating master data.",
        )

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        self.rng = random.Random(options["seed"])
        self.warnings = []
        self.batch_counters = {}
        # Ceiling for every simulated moment; see `_stamp`. Fixed at the
        # start of the run, so it is always earlier than any marker taken
        # later on.
        self.latest_stamp = timezone.now().astimezone(IST)

        date_from = datetime.date.fromisoformat(options["date_from"])
        date_to = (
            datetime.date.fromisoformat(options["date_to"])
            if options["date_to"]
            else timezone.now().astimezone(IST).date()
        )

        # Everything - the reset, the provisional mappings, the coil
        # receipts and every batch - is one transaction, so a precondition
        # that fails half way leaves the database exactly as it was.
        with transaction.atomic():
            if options["reset"]:
                call_command("reset_process_data", yes=True)

            date_from = self._resolve_start(date_from, options)
            if date_from > date_to:
                self.stdout.write(self.style.SUCCESS(f"Nothing to generate: already current through {date_to}."))
                return

            self.user = self._seeding_user()
            self._load_masters()
            self._ensure_mappings(allow_provisional=options["provisional_mappings"])

            days = self._working_days(date_from, date_to)
            if not days:
                raise CommandError(f"No working days (Mon-Sat) between {date_from} and {date_to}.")
            plan = self._plan_batches(days, options["per_day"], date_to)
            self._check_wire_serials(len(plan))
            self._receive_coils(plan, date_from, date_to)

            for entry in plan:
                self._run_batch(entry)

            self._print_warnings()
            self._assert_chain_is_intact()
            self._print_summary()

    # ------------------------------------------------------------------
    # Preconditions
    # ------------------------------------------------------------------
    def _resolve_start(self, date_from, options):
        """`--extend` picks up the day after the newest existing batch and
        never touches what is already there. Without it, a database that
        already holds process rows is refused."""
        if options["extend"]:
            newest = RollingBatch.objects.order_by("-created_at").first()
            if newest is None:
                return date_from
            return max(date_from, newest.created_at.astimezone(IST).date() + datetime.timedelta(days=1))
        if not options["reset"] and self._process_tables_have_rows():
            raise CommandError(
                "Process tables are not empty. Re-run with --reset to clear them first, "
                "or --extend to add only the dates that are missing."
            )
        return date_from

    def _process_tables_have_rows(self):
        return any(process.model.objects.exists() for process in PROCESSES)

    def _seeding_user(self):
        user = User.objects.filter(is_superuser=True).order_by("pk").first()
        if user is None:
            raise CommandError(
                "No superuser exists to own the generated history. Create one with "
                "`python manage.py createsuperuser` first."
            )
        return user

    def _load_masters(self):
        """Read every master this run needs. A master table that cannot
        supply a step is named here and the run stops - the generator does
        not create master rows."""
        self.traveller_nos = list(TravellerNo.objects.filter(is_active=True).order_by("traveller_no_id"))
        self.finishes = list(SurfaceFinish.objects.filter(is_active=True).order_by("finish_id"))
        self.diameters = list(DiameterMaster.objects.filter(status="Active").order_by("diameter_mm"))
        self.racks = list(RackMaster.objects.filter(is_active=True).order_by("rack_code"))

        missing = []
        if not TravellerType.objects.filter(is_active=True).exists():
            missing.append("masters.TravellerType (no active rows)")
        if not self.traveller_nos:
            missing.append("masters.TravellerNo (no active rows)")
        if not self.finishes:
            missing.append("masters.SurfaceFinish (no active rows)")
        if not self.diameters:
            missing.append("masters.DiameterMaster (no Active rows)")
        if not self.racks:
            missing.append("masters.RackMaster (no active rows)")
        if not WireSerialMaster.objects.filter(status="Available").exists():
            missing.append("masters.WireSerialMaster (no Available serials)")

        # A process needs machines only if one of its screens shows a
        # Machine column - Heat Treatment records none, and the registry
        # is what says so.
        self.machines_by_process = {}
        for process in PROCESSES:
            if not self._records_a_machine(process):
                continue
            machines = list(Machine.active.filter(stage=process.slug, is_operational=True).order_by("code"))
            if not machines:
                missing.append(f"masters.Machine (no operational rows for stage '{process.slug}')")
            self.machines_by_process[process.slug] = machines

        if missing:
            raise CommandError(
                "Master data is missing; nothing was written. Load it with `seed_masters` "
                "(or the real master import) before generating history:\n  " + "\n  ".join(missing)
            )

    @staticmethod
    def _records_a_machine(process):
        columns = tuple(process.main_columns) + tuple(process.complete_columns)
        return any(column.accessor.split(".")[0] == "machine" for column in columns)

    def _ensure_mappings(self, *, allow_provisional):
        """Rolling refuses a traveller type with no raw-material mapping.
        Only one mapping is confirmed, so the rest need a provisional one -
        but only when the operator has explicitly asked for that."""
        missing = list(
            TravellerType.objects.filter(is_active=True, mapping__isnull=True).order_by("seq_no")
        )
        if not missing:
            return
        if not allow_provisional:
            listing = "\n  ".join(f"{t.seq_no:>3}  {t.name}" for t in missing)
            raise CommandError(
                f"{len(missing)} active traveller types have no DiameterTravellerMapping, so they "
                "cannot be rolled. Nothing was written.\n\n"
                "Import the real mappings:\n"
                "  python manage.py import_traveller_mappings <csv>   "
                "# columns: seq_no,diameter_mm,f_thickness_mm,f_width_mm\n\n"
                "Or re-run with --provisional-mappings to generate a guess for them.\n\n"
                f"Unmapped traveller types:\n  {listing}"
            )

        invented = []
        for traveller_type in missing:
            # Positionally chosen from the diameter master that is actually
            # loaded - no diameter value is written here.
            diameter = self.diameters[traveller_type.seq_no % len(self.diameters)]
            DiameterTravellerMapping.objects.create(
                traveller_type=traveller_type,
                raw_material=diameter,
                f_thickness_mm=money(diameter.diameter_mm * THICKNESS_RATIO),
                f_width_mm=money(diameter.diameter_mm * WIDTH_RATIO),
            )
            invented.append(f"{traveller_type.seq_no:>3}  {traveller_type.name:<38} -> {diameter.raw_material_id}")

        self.warnings.append(
            f"{len(invented)} PROVISIONAL traveller-type mappings were created because no real mapping "
            "exists for them. Existing mappings were left untouched. These are a guess (diameter picked "
            "by seq_no, F-Thickness = dia x 0.44, F-Width = dia x 1.90) and MUST be replaced with the "
            "business's real values:\n"
            "    python manage.py import_traveller_mappings <csv>   "
            "# columns: seq_no,diameter_mm,f_thickness_mm,f_width_mm\n  "
            + "\n  ".join(invented)
        )

    def _check_wire_serials(self, needed):
        available = WireSerialMaster.objects.filter(status="Available").count()
        if available < needed:
            raise CommandError(
                f"{needed} batches need {needed} wire serials but only {available} are Available in "
                "masters.WireSerialMaster. Load the next prefix block before seeding; nothing was written."
            )

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------
    def _working_days(self, date_from, date_to):
        days, day = [], date_from
        while day <= date_to:
            if day.weekday() != SUNDAY:
                days.append(day)
            day += datetime.timedelta(days=1)
        return days

    def _plan_batches(self, days, per_day, date_to):
        """One entry per batch: which traveller type, how much wire, and how
        far down the pipeline its age lets it get."""
        types = list(TravellerType.objects.filter(is_active=True, mapping__isnull=False).order_by("seq_no"))
        if not types:
            raise CommandError("No active traveller type has a mapping, so no batch can be rolled.")

        plan = []
        for day in days:
            for _ in range(per_day):
                index = len(plan)
                age = (date_to - day).days
                target, complete = next((t, c) for threshold, t, c in AGE_BANDS if age >= threshold)
                plan.append(
                    {
                        "date": day,
                        # Cycling by position guarantees every active type is
                        # used once the plan is at least as long as the master.
                        "traveller_type": types[index % len(types)],
                        "traveller_no": self.traveller_nos[index % len(self.traveller_nos)],
                        "finish": self.finishes[index % len(self.finishes)],
                        "required_box": index % REQUIRED_BOX_RANGE[1] + REQUIRED_BOX_RANGE[0],
                        "draws": [
                            money(self.rng.uniform(float(DRAW_WEIGHT_RANGE[0]), float(DRAW_WEIGHT_RANGE[1])))
                            for _ in range(self.rng.randint(*DRAWS_PER_BATCH))
                        ],
                        "target": min(target, len(PROCESSES) - 1),
                        "complete": complete,
                    }
                )
        self._leave_some_open(plan)
        return plan

    def _leave_some_open(self, plan):
        """One batch in five is left open at whatever process its age band
        reached. Counted within each band: the oldest band holds most of the
        batches, so a single global count would leave short bands with none."""
        bands = {}
        for entry in plan:
            bands.setdefault(entry["target"], []).append(entry)
        for band in bands.values():
            for position, entry in enumerate(band):
                if position % LEAVE_OPEN_EVERY == LEAVE_OPEN_EVERY - 1:
                    entry["complete"] = False
            if all(entry["complete"] for entry in band):
                band[0]["complete"] = False

    def _receive_coils(self, plan, date_from, date_to):
        """Receive coils through `masters.services.receive_coil`, enough to
        cover what the planned batches will draw from each diameter. Demand
        is computed first so stock always covers the batches."""
        demand = {}
        for entry in plan:
            diameter = entry["traveller_type"].mapping.raw_material
            demand[diameter.raw_material_id] = demand.get(diameter.raw_material_id, Decimal("0")) + sum(
                entry["draws"], Decimal("0")
            )

        earliest = date_from - datetime.timedelta(days=COIL_LEAD_DAYS)
        span = max((date_to - earliest).days, 1)
        received = 0
        for raw_material_id, required in sorted(demand.items()):
            diameter = DiameterMaster.objects.get(pk=raw_material_id)
            # Headroom: a draw is taken from a single coil, so part-used
            # coils leave stock the next batch cannot fully use.
            target_stock = required * Decimal("1.4") + Decimal("100")
            minimum_coils = self.rng.randint(*COILS_PER_DIAMETER)
            while diameter.total_stock < target_stock or diameter.active_coils < minimum_coils:
                masters_services.receive_coil(
                    raw_material=diameter,
                    weight_kg=money(self.rng.uniform(float(COIL_WEIGHT_RANGE[0]), float(COIL_WEIGHT_RANGE[1]))),
                    rack=self.racks[received % len(self.racks)],
                    supplier=SUPPLIERS[received % len(SUPPLIERS)],
                    received_date=earliest + datetime.timedelta(days=self.rng.randint(0, span)),
                )
                diameter.refresh_from_db()
                received += 1
        self.stdout.write(f"  Coils received: {received} across {len(demand)} diameters")

    # ------------------------------------------------------------------
    # Backdating
    # ------------------------------------------------------------------
    def _marker(self):
        """The instant a step begins. Everything a ledger table gains after
        it belongs to that step. Simulated stamps are clamped to the past
        (see `_stamp`), so a row that has already been backdated can never
        sit at or after a later marker and be picked up twice."""
        return timezone.now()

    def _backdate(self, stamp, marker, record=None, wire_serial=""):
        """`auto_now_add` ignores `save()`, so every row the step just wrote
        is moved back to the simulated moment with an UPDATE."""
        for model in BACKDATED_LEDGERS:
            model.objects.filter(created_at__gte=marker).update(created_at=stamp)
        if wire_serial:
            WireSerialMaster.objects.filter(serial_no=wire_serial).update(used_at=stamp)
        if record is not None:
            # Only concrete columns can be UPDATEd; the terminal process
            # serves `completed_at` as a property over `updated_at`.
            columns = {field.name for field in type(record)._meta.concrete_fields}
            fields = {}
            if "created_at" in columns:
                fields["created_at"] = stamp
            if "completed_at" in columns and getattr(record, "completed_at", None) is not None:
                fields["completed_at"] = stamp + COMPLETE_OFFSET
            if "operation_date" in columns:
                fields["operation_date"] = stamp.date()
            if "updated_at" in columns:
                fields["updated_at"] = stamp
            type(record).objects.filter(pk=record.pk).update(**fields)
            record.refresh_from_db()

    def _stamp(self, entry, process):
        """The moment this process worked on this batch: the batch's start
        date plus the process's offset, at a plausible time of day.

        Clamped to the moment the run began. A process that works `n` days
        after the batch starts would otherwise stamp the newest batches into
        the future, and `_backdate` identifies the rows a step wrote by
        "created since the step began" - a row dated ahead of a later marker
        would be picked up a second time and re-stamped.
        """
        offset = DAY_OFFSET_PER_PROCESS[min(process.index, len(DAY_OFFSET_PER_PROCESS) - 1)]
        day = entry["date"] + datetime.timedelta(days=offset)
        stamp = datetime.datetime.combine(
            day, datetime.time(self.rng.randint(*INITIATE_HOURS), self.rng.randint(0, 59)), tzinfo=IST
        )
        return min(stamp, self.latest_stamp)

    # ------------------------------------------------------------------
    # Execution - one batch, through the real services
    # ------------------------------------------------------------------
    def _run_batch(self, entry):
        record = self._initiate_rolling(entry)
        for step in range(1, entry["target"] + 1):
            self._complete(PROCESSES[step - 1], record, entry)
            record = self._initiate(PROCESSES[step], record.handover_lot, entry)
        if entry["complete"]:
            self._complete(PROCESSES[entry["target"]], record, entry)

    def _initiate_rolling(self, entry):
        process = PROCESSES[0]
        stamp = self._stamp(entry, process)
        marker = self._marker()
        coil_weights = self._pick_coils(entry)
        batch = rolling_services.initiate_rolling_batch(
            traveller_type=entry["traveller_type"],
            traveller_no=entry["traveller_no"],
            finish=entry["finish"],
            required_box=entry["required_box"],
            wire_weight_issued_kg=sum((weight for _, weight in coil_weights), Decimal("0")),
            coil_weights=coil_weights,
            user=self.user,
        )
        self._backdate(stamp, marker, batch, wire_serial=batch.wire_serial)
        lot = batch.handover_lot
        type(lot).objects.filter(pk=lot.pk).update(created_at=stamp, updated_at=stamp)
        return batch

    def _pick_coils(self, entry):
        """One draw per coil, never the same coil twice in a batch, and never
        more than the coil actually holds."""
        diameter = entry["traveller_type"].mapping.raw_material
        coils = list(
            CoilMaster.objects.filter(raw_material=diameter, status="In Stock").order_by("coil_display_number")
        )
        picks, used = [], set()
        for wanted in entry["draws"]:
            candidate = next((c for c in coils if c.coil_id not in used and c.weight_kg >= wanted), None)
            if candidate is None:
                candidate = max(
                    (c for c in coils if c.coil_id not in used and c.weight_kg > 0),
                    key=lambda c: c.weight_kg, default=None,
                )
                if candidate is None:
                    break
                wanted = candidate.weight_kg
            used.add(candidate.coil_id)
            picks.append((candidate.coil_id, wanted))
        if not picks:
            raise CommandError(
                f"No In-Stock coil remains for {diameter.raw_material_id}; nothing was written."
            )
        return picks

    def _initiate(self, process, lot, entry):
        stamp = self._stamp(entry, process)
        marker = self._marker()
        if process.next is None:
            record = self._receive_finished_goods(process, lot, entry)
        else:
            record = production_services.initiate_stage(
                process, lot, self.user, **self._initiate_fields(process, entry, stamp)
            )
        self._backdate(stamp, marker, record)
        return record

    def _initiate_fields(self, process, entry, stamp):
        """Only the fields a process's own Initiate screen asks for."""
        model_fields = {field.name for field in process.model._meta.get_fields()}
        fields = {}
        if "operation_date" in model_fields:
            fields["operation_date"] = stamp.date()
        machines = self.machines_by_process.get(process.slug)
        if machines and "machine" in model_fields:
            fields["machine"] = machines[self._next_index(f"machine:{process.slug}") % len(machines)]
        if "surface_finish" in model_fields:
            fields["surface_finish"] = entry["finish"]
        if process.batch_prefix:
            sequence = self._next_index(f"{process.batch_prefix}:{stamp:%y%m}") + 1
            batch_number = f"{process.batch_prefix}-{stamp:%y%m}-{sequence % 1000:03d}"
            for name in ("batch_number", "batch_no"):
                if name in model_fields:
                    fields[name] = batch_number
        return fields

    def _next_index(self, key):
        """Round-robin / running counters, so machines rotate and batch
        numbers run in sequence rather than colliding at random."""
        value = self.batch_counters.get(key, 0)
        self.batch_counters[key] = value + 1
        return value

    def _receive_finished_goods(self, process, lot, entry):
        from apps.master_data.models import ProductMaster

        incoming = production_services.incoming_record_for(process, lot)
        product = ProductMaster.active.first()
        if product is None:
            raise CommandError("No active master_data.ProductMaster row exists; Finished Goods cannot be received.")
        return fg_services.receive_finished_goods(
            lot=lot,
            product=product,
            accepted_quantity=incoming.output_weight,
            rejected_quantity=Decimal("0"),
            location=inventory_services._default_location(process.slug),
            rack=None, shelf=None, tray=None,
            user=self.user,
            remarks=f"Received from {process.previous.label}",
        )

    def _complete(self, process, record, entry):
        # Completion follows initiation by a couple of hours, but is capped
        # at the start of the run for the same reason `_stamp` is.
        stamp = min(self._stamp(entry, process) + COMPLETE_OFFSET, self.latest_stamp)
        marker = self._marker()
        if process.next is None:
            fg_services.approve_finished_goods(record, self.user, mark_available=True)
        else:
            self._apply_completion_values(process, record, entry)
            if process.previous is None:
                rolling_services.complete_rolling_batch(
                    record,
                    rolled_thickness_mm=record.f_thickness_mm,
                    rolled_width_mm=record.f_width_mm,
                    finished_weight_kg=record.finished_weight_kg,
                    user=self.user,
                )
            else:
                production_services.complete_stage(record, self.user)
        record.refresh_from_db()
        self._backdate(stamp, marker, record)
        return record

    def _apply_completion_values(self, process, record, entry):
        """Yield loss plus whatever else this process records at completion.
        Which fields those are is read off the model, so a process that
        records something else gets it filled without a slug check here."""
        output = money(record.received_weight * Decimal(str(self.rng.uniform(*YIELD_RANGE))))
        model_fields = {field.name for field in process.model._meta.get_fields()}
        updates = {}
        if "finished_weight_kg" in model_fields:
            # Rolling's completion service takes this as an argument.
            record.finished_weight_kg = output
        if "output_quantity" in model_fields:
            updates["output_quantity"] = output
        if "traveller_length_mm" in model_fields:
            updates["traveller_length_mm"] = money(
                self.rng.uniform(float(TRAVELLER_LENGTH_RANGE[0]), float(TRAVELLER_LENGTH_RANGE[1]))
            )
        if "traveller_weight_kg" in model_fields:
            updates["traveller_weight_kg"] = output
        if "colour" in model_fields:
            updates["colour"] = COLOURS[entry["required_box"] % len(COLOURS)]
        for name, value in updates.items():
            setattr(record, name, value)
        if updates:
            record.save(update_fields=list(updates))

    # ------------------------------------------------------------------
    # Acceptance
    # ------------------------------------------------------------------
    def _assert_chain_is_intact(self):
        """Nothing may fall out of the pipeline: every row on process N's
        Complete Table is either an incoming row on N+1 or a record of N+1.
        This is the screen-level contract, asserted for every consecutive
        pair in the registry."""
        broken = []
        for process, following in zip(PROCESSES, PROCESSES[1:]):
            waiting = {r.handover_lot.pk for r in following.incoming_queryset(None) if r.handover_lot}
            taken = set(following.model.objects.values_list("lot_id", flat=True))
            for record in process.complete_queryset(None):
                lot = record.handover_lot
                if lot is None or (lot.pk not in waiting and lot.pk not in taken):
                    broken.append(f"{process.label} {record.wire_serial} is not visible at {following.label}")
        if broken:
            raise CommandError("Handover chain is broken; nothing was written:\n  " + "\n  ".join(broken))
        self.stdout.write(self.style.SUCCESS("Chain check: every completed record is visible at the next process."))

    def _print_warnings(self):
        for warning in self.warnings:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("=" * 78))
            self.stdout.write(self.style.WARNING("WARNING - FABRICATED MASTER DATA"))
            self.stdout.write(self.style.WARNING("=" * 78))
            self.stdout.write(self.style.WARNING(warning))
            self.stdout.write(self.style.WARNING("=" * 78))

    def _process_dates(self, process):
        """Earliest and latest date shown on this process's two screens."""
        bounds = process.model.objects.aggregate(first=Min("created_at"), last=Max("created_at"))
        if bounds["first"] is None:
            return "-", "-"
        return (
            f"{bounds['first'].astimezone(IST):%Y-%m-%d}",
            f"{bounds['last'].astimezone(IST):%Y-%m-%d}",
        )

    def _print_summary(self):
        header = (
            f"{'Process':<16}{'Incoming':>9}{'In progress':>12}{'Completed':>10}"
            f"{'Earliest':>13}{'Latest':>13}"
        )
        self.stdout.write("")
        self.stdout.write(header)
        self.stdout.write("-" * len(header))
        for process in PROCESSES:
            incoming = process.incoming_queryset(None)
            earliest, latest = self._process_dates(process)
            self.stdout.write(
                f"{process.label:<16}"
                f"{(incoming.count() if incoming is not None else 0):>9}"
                f"{process.main_queryset(None).count():>12}"
                f"{process.complete_queryset(None).count():>10}"
                f"{earliest:>13}{latest:>13}"
            )

        used_types = RollingBatch.objects.values("traveller_type").distinct().count()
        active_types = TravellerType.objects.filter(is_active=True).count()
        span = RollingBatch.objects.aggregate(first=Min("created_at"), last=Max("created_at"))
        self.stdout.write("")
        self.stdout.write(f"Traveller types used: {used_types} / {active_types} active")
        if span["first"] is None:
            self.stdout.write("Batches: 0")
            return
        self.stdout.write(
            f"Batches: {RollingBatch.objects.count()} "
            f"from {span['first'].astimezone(IST):%Y-%m-%d} to {span['last'].astimezone(IST):%Y-%m-%d}"
        )
        if used_types < active_types:
            raise CommandError(
                f"Only {used_types} of {active_types} active traveller types appear in a Rolling batch; "
                "widen the date range or raise --per-day so every type is exercised. Nothing was written."
            )
