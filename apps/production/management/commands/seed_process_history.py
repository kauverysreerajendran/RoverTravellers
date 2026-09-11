"""Generate a realistic process history, through the real services.

Every batch this command creates goes through exactly the service
functions the screens call - `initiate_rolling_batch`,
`complete_rolling_batch`, `production.services.initiate_stage`,
`complete_stage`/`handover`, `receive_finished_goods` - so a successful
run is itself proof that the whole pipeline works. Nothing is inserted
straight into the ORM except the timestamp backdating at the end of each
step, which `auto_now_add` fields make impossible to do any other way.

The pipeline order is never named here: the command walks `PROCESSES` and
uses `process.previous`/`process.next`, so a sixth process added to the
registry is generated and asserted without touching this file.

Usage:
    python manage.py seed_masters
    python manage.py seed_process_history --reset          # first time
    python manage.py seed_process_history --extend         # daily top-up
"""

import datetime
import random
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.finished_goods import services as fg_services
from apps.inventory import services as inventory_services
from apps.inventory.models import FinishedGoodsStock, StockTransaction, WIPStock
from apps.masters import services as masters_services
from apps.masters.management.commands.seed_masters import DIAMETERS_MM
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

# How many days after a batch starts each process records its operation.
DAY_OFFSET_PER_PROCESS = [0, 2, 4, 6, 8]

# How far a batch has got, by how old it is. The index is into PROCESSES,
# so the bands describe "reached process N", not a named stage.
AGE_BANDS = [
    (12, 4, True),   # >= 12 days old: received and approved at the last process
    (9, 3, True),
    (6, 2, True),
    (4, 1, True),
    (2, 0, True),
    (0, 0, False),   # started in the last day or two: still open at the origin
]

# One batch in every five is left open at whatever process its age band
# reached, so every Main Table shows in-progress rows as well as incoming.
LEAVE_OPEN_EVERY = 5


def money(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class Command(BaseCommand):
    help = "Generate realistic process history from --from to --to, through the real service layer."

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="date_from", default=DEFAULT_FROM.isoformat())
        parser.add_argument("--to", dest="date_to", default="")
        parser.add_argument("--per-day", type=int, default=2, help="Batches started per working day (Mon-Sat).")
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--reset", action="store_true", help="Run reset_process_data --yes first.")
        parser.add_argument(
            "--extend", action="store_true",
            help="Only generate dates after the newest existing batch, leaving existing rows untouched.",
        )
        parser.add_argument(
            "--no-provisional-mappings", action="store_true",
            help="Abort instead of inventing mappings for traveller types that have none.",
        )

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        self.rng = random.Random(options["seed"])
        self.warnings = []

        date_from = datetime.date.fromisoformat(options["date_from"])
        date_to = (
            datetime.date.fromisoformat(options["date_to"])
            if options["date_to"]
            else timezone.now().astimezone(IST).date()
        )

        if options["reset"]:
            call_command("reset_process_data", yes=True)

        if options["extend"]:
            newest = RollingBatch.objects.order_by("-created_at").first()
            if newest is not None:
                date_from = max(date_from, newest.created_at.astimezone(IST).date() + datetime.timedelta(days=1))
        elif not options["reset"] and self._process_tables_have_rows():
            raise CommandError(
                "Process tables are not empty. Re-run with --reset to clear them first, "
                "or --extend to add only the dates that are missing."
            )

        if date_from > date_to:
            self.stdout.write(self.style.SUCCESS(f"Nothing to generate: already current through {date_to}."))
            return

        self.user = self._seeding_user()
        self._ensure_mappings(abort=options["no_provisional_mappings"])
        self._ensure_machines()

        days = self._working_days(date_from, date_to)
        if not days:
            raise CommandError(f"No working days between {date_from} and {date_to}.")
        plan = self._plan_batches(days, options["per_day"], date_to)
        self._check_wire_serials(len(plan))
        self._ensure_racks()
        self._ensure_coils(plan, date_from, date_to)

        with transaction.atomic():
            for index, entry in enumerate(plan):
                self._run_batch(index, entry)

        self._print_warnings()
        self._assert_chain_is_intact()
        self._print_summary()

    # ------------------------------------------------------------------
    # Preconditions
    # ------------------------------------------------------------------
    def _process_tables_have_rows(self):
        return any(process.model.objects.exists() for process in PROCESSES)

    def _seeding_user(self):
        user = User.objects.filter(is_superuser=True).order_by("pk").first()
        if user is None:
            user = User.objects.create_superuser(
                username="demo_seeder", email="demo_seeder@example.com", password=User.objects.make_random_password()
            )
            self.warnings.append(
                "No superuser existed, so the user 'demo_seeder' was created to own the generated "
                "history. Set its password or delete it once real users exist."
            )
        return user

    def _ensure_mappings(self, *, abort):
        """Rolling refuses a traveller type with no raw-material mapping, and
        only one mapping is confirmed, so the rest get a provisional one."""
        official = [Decimal(value) for value in DIAMETERS_MM]
        available = {
            d.diameter_mm: d for d in DiameterMaster.objects.filter(diameter_mm__in=official)
        }
        usable = [available[value] for value in official if value in available]
        if not usable:
            raise CommandError("No official diameters in DiameterMaster. Run seed_masters first.")

        missing = list(
            TravellerType.objects.filter(is_active=True, mapping__isnull=True).order_by("seq_no")
        )
        if not missing:
            return
        if abort:
            raise CommandError(
                f"{len(missing)} active traveller types have no DiameterTravellerMapping. "
                "Import the real mappings with `import_traveller_mappings <csv>` or drop "
                "--no-provisional-mappings."
            )

        invented = []
        for traveller_type in missing:
            diameter = usable[traveller_type.seq_no % len(usable)]
            DiameterTravellerMapping.objects.create(
                traveller_type=traveller_type,
                raw_material=diameter,
                f_thickness_mm=money(diameter.diameter_mm * THICKNESS_RATIO),
                f_width_mm=money(diameter.diameter_mm * WIDTH_RATIO),
            )
            invented.append(f"{traveller_type.seq_no:>3}  {traveller_type.name:<38} -> {diameter.raw_material_id}")

        self.warnings.append(
            f"{len(invented)} PROVISIONAL traveller-type mappings were invented because no real mapping "
            "exists for them. They are a guess (diameter picked by seq_no, F-Thickness = dia x 0.44, "
            "F-Width = dia x 1.90) and MUST be replaced with the business's real values:\n"
            "    python manage.py import_traveller_mappings <csv>   "
            "# columns: seq_no,diameter_mm,f_thickness_mm,f_width_mm\n  "
            + "\n  ".join(invented)
        )

    def _ensure_machines(self):
        """Machines are master data, but `seed_masters` does not create any
        and Forming/Finishing record one. Anything invented here is flagged
        the same way a provisional mapping is."""
        from apps.master_data.models import Plant

        self.machines_by_process = {}
        invented = []
        for process in PROCESSES:
            machines = list(Machine.active.filter(stage=process.slug).order_by("code"))
            if not machines and process.slug in dict(Machine.STAGE_CHOICES):
                plant = Plant.active.first() or Plant.objects.create(code="PLANT", name="Plant")
                for suffix in ("A", "B"):
                    code = f"{process.slug[:3].upper()}-{suffix}"
                    machine, _ = Machine.objects.get_or_create(
                        code=code,
                        defaults={"name": f"{process.label} {suffix}", "stage": process.slug, "plant": plant},
                    )
                    machines.append(machine)
                    invented.append(f"{code} ({process.label})")
            self.machines_by_process[process.slug] = machines
        if invented:
            self.warnings.append(
                "PROVISIONAL machines were created because none existed for these processes: "
                + ", ".join(invented)
                + ". Replace them with the real machine master."
            )

    def _ensure_racks(self):
        existing = RackMaster.objects.count()
        for number in range(existing + 1, 7):
            RackMaster.objects.get_or_create(rack_code=f"R{number}", defaults={"capacity": 10})
        self.racks = list(RackMaster.objects.order_by("rack_code"))

    def _check_wire_serials(self, needed):
        available = WireSerialMaster.objects.filter(status="Available").count()
        if available < needed:
            raise CommandError(
                f"{needed} batches need {needed} wire serials but only {available} are Available. "
                "Load the next prefix block before seeding; nothing has been written."
            )

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------
    def _working_days(self, date_from, date_to):
        days, day = [], date_from
        while day <= date_to:
            if day.weekday() < 6:  # Monday-Saturday
                days.append(day)
            day += datetime.timedelta(days=1)
        return days

    def _plan_batches(self, days, per_day, date_to):
        """One entry per batch: which traveller type, how much wire, and how
        far down the pipeline its age lets it get."""
        types = list(TravellerType.objects.filter(is_active=True, mapping__isnull=False).order_by("seq_no"))
        if not types:
            raise CommandError("No active traveller types with a mapping.")
        traveller_nos = list(TravellerNo.objects.filter(is_active=True).order_by("traveller_no_id"))
        finishes = list(SurfaceFinish.objects.filter(is_active=True).order_by("finish_id"))
        if not traveller_nos or not finishes:
            raise CommandError("Traveller numbers and surface finishes must be seeded first.")

        plan = []
        for day in days:
            for _ in range(per_day):
                index = len(plan)
                traveller_type = types[index % len(types)]
                draws = [money(self.rng.uniform(10, 45)) for _ in range(self.rng.randint(1, 3))]
                age = (date_to - day).days
                target, complete = next((t, c) for threshold, t, c in AGE_BANDS if age >= threshold)
                target = min(target, len(PROCESSES) - 1)
                plan.append(
                    {
                        "date": day,
                        "traveller_type": traveller_type,
                        "traveller_no": traveller_nos[index % len(traveller_nos)],
                        "finish": finishes[index % len(finishes)],
                        "required_box": index % 6 + 1,
                        "draws": draws,
                        "target": target,
                        "complete": complete,
                    }
                )
        self._leave_some_open(plan)
        return plan

    def _leave_some_open(self, plan):
        """One batch in every five is left initiated-but-not-completed at
        whatever process its age band reached, so every Main Table shows
        in-progress rows next to its incoming ones. Counted within each
        band: the oldest band holds most of the batches, so a global count
        would leave the short bands with none."""
        bands = {}
        for entry in plan:
            bands.setdefault(entry["target"], []).append(entry)
        for band in bands.values():
            for position, entry in enumerate(band):
                if position % LEAVE_OPEN_EVERY == LEAVE_OPEN_EVERY - 1:
                    entry["complete"] = False
            if all(entry["complete"] for entry in band):
                band[0]["complete"] = False

    def _ensure_coils(self, plan, date_from, date_to):
        """Receive coils through `masters.services.receive_coil`, enough to
        cover what the planned batches will draw from each diameter."""
        demand = {}
        for entry in plan:
            diameter = entry["traveller_type"].mapping.raw_material
            demand[diameter.raw_material_id] = demand.get(diameter.raw_material_id, Decimal("0")) + sum(
                entry["draws"], Decimal("0")
            )

        earliest = date_from - datetime.timedelta(days=14)
        span = (date_to - earliest).days or 1
        received = 0
        for raw_material_id, required in sorted(demand.items()):
            diameter = DiameterMaster.objects.get(pk=raw_material_id)
            # Headroom: a draw can only come from one coil, so part-used
            # coils leave stock that the next batch cannot fully use.
            target_stock = required * Decimal("1.4") + Decimal("100")
            minimum_coils = self.rng.randint(3, 6)
            while diameter.total_stock < target_stock or diameter.active_coils < minimum_coils:
                masters_services.receive_coil(
                    raw_material=diameter,
                    weight_kg=money(self.rng.uniform(40, 95)),
                    rack=self.racks[received % len(self.racks)],
                    supplier=SUPPLIERS[received % len(SUPPLIERS)],
                    received_date=earliest + datetime.timedelta(days=self.rng.randint(0, span)),
                )
                diameter.refresh_from_db()
                received += 1
        self.stdout.write(f"  Coils received: {received} across {len(demand)} diameters")

    # ------------------------------------------------------------------
    # Execution - one batch, through the real services
    # ------------------------------------------------------------------
    def _run_batch(self, index, entry):
        record = self._initiate_rolling(entry)
        for step in range(1, entry["target"] + 1):
            previous_process = PROCESSES[step - 1]
            self._complete(previous_process, record, entry)
            record = self._initiate(PROCESSES[step], record.handover_lot, entry)
        if entry["complete"]:
            self._complete(PROCESSES[entry["target"]], record, entry)

    def _stamp(self, entry, process):
        """The moment this process worked on this batch: the batch's start
        date plus the process's offset, at a plausible time of day."""
        offset = DAY_OFFSET_PER_PROCESS[min(process.index, len(DAY_OFFSET_PER_PROCESS) - 1)]
        day = entry["date"] + datetime.timedelta(days=offset)
        # Initiation runs 08:00-16:00 so that completion, two hours later,
        # still lands inside the working day.
        return datetime.datetime.combine(
            day, datetime.time(self.rng.randint(8, 15), self.rng.randint(0, 59)), tzinfo=IST
        )

    def _backdate(self, stamp, marker, record=None):
        """`auto_now_add` ignores `save()`, so the rows a service just wrote
        are moved back to `stamp` with an UPDATE. Everything written since
        `marker` belongs to the step that just ran."""
        for model in (AuditLog, OperationStatusHistory, StockTransaction, WIPStock, FinishedGoodsStock):
            model.objects.filter(created_at__gte=marker).update(created_at=stamp)
        WireSerialMaster.objects.filter(used_at__gte=marker).update(used_at=stamp)
        if record is not None:
            # Only concrete columns can be UPDATEd; the terminal process
            # serves `completed_at` as a property over `updated_at`.
            columns = {f.name for f in type(record)._meta.concrete_fields}
            fields = {"created_at": stamp}
            if "completed_at" in columns and getattr(record, "completed_at", None) is not None:
                fields["completed_at"] = stamp + datetime.timedelta(hours=2)
            if "operation_date" in columns:
                fields["operation_date"] = stamp.date()
            if "updated_at" in columns:
                fields["updated_at"] = stamp
            type(record).objects.filter(pk=record.pk).update(**fields)
            record.refresh_from_db()

    def _initiate_rolling(self, entry):
        process = PROCESSES[0]
        stamp = self._stamp(entry, process)
        marker = timezone.now()
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
        self._backdate(stamp, marker, batch)
        lot = batch.handover_lot
        type(lot).objects.filter(pk=lot.pk).update(created_at=stamp)
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
                f"No coil stock left for {diameter.raw_material_id}; nothing further was written."
            )
        return picks

    def _initiate(self, process, lot, entry):
        stamp = self._stamp(entry, process)
        marker = timezone.now()
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
        model_fields = {f.name for f in process.model._meta.get_fields()}
        fields = {}
        if "operation_date" in model_fields:
            fields["operation_date"] = stamp.date()
        machines = self.machines_by_process.get(process.slug) or []
        if "machine" in model_fields and machines:
            fields["machine"] = machines[entry["required_box"] % len(machines)]
        if "surface_finish" in model_fields:
            fields["surface_finish"] = entry["finish"]
        if process.batch_prefix:
            batch_number = f"{process.batch_prefix}-{stamp:%y%m}-{self.rng.randint(1, 999):03d}"
            for name in ("batch_number", "batch_no"):
                if name in model_fields:
                    fields[name] = batch_number
        return fields

    def _receive_finished_goods(self, process, lot, entry):
        from apps.master_data.models import ProductMaster

        incoming = production_services.incoming_record_for(process, lot)
        product = ProductMaster.active.first()
        if product is None:
            raise CommandError("No ProductMaster row exists; Finished Goods cannot be received.")
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
        stamp = self._stamp(entry, process) + datetime.timedelta(hours=2)
        marker = timezone.now()
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
        """Yield loss plus whatever else this process records at completion."""
        output = money(record.received_weight * Decimal(str(self.rng.uniform(0.960, 0.995))))
        model_fields = {f.name for f in process.model._meta.get_fields()}
        if "finished_weight_kg" in model_fields:
            record.finished_weight_kg = output
        if "output_quantity" in model_fields:
            record.output_quantity = output
            record.save(update_fields=["output_quantity"])
        if "traveller_length_mm" in model_fields:
            record.traveller_length_mm = money(self.rng.uniform(400, 900))
            record.save(update_fields=["traveller_length_mm"])
        if "traveller_weight_kg" in model_fields:
            record.traveller_weight_kg = output
            record.save(update_fields=["traveller_weight_kg"])
        if "colour" in model_fields:
            record.colour = COLOURS[entry["required_box"] % len(COLOURS)]
            record.save(update_fields=["colour"])

    # ------------------------------------------------------------------
    # Acceptance
    # ------------------------------------------------------------------
    def _assert_chain_is_intact(self):
        """Nothing may fall out of the pipeline: everything a process
        completed is either waiting at the next process or has been taken
        up by it."""
        broken = []
        for process, following in zip(PROCESSES, PROCESSES[1:]):
            waiting = {r.handover_lot.pk for r in following.incoming_queryset(None) if r.handover_lot}
            taken = set(following.model.objects.values_list("lot_id", flat=True))
            for record in process.complete_queryset(None):
                lot = record.handover_lot
                if lot is None or (lot.pk not in waiting and lot.pk not in taken):
                    broken.append(f"{process.label} {record.wire_serial} is not visible at {following.label}")
        if broken:
            raise CommandError("Handover chain is broken:\n  " + "\n  ".join(broken))
        self.stdout.write(self.style.SUCCESS("Chain check: every completed record is visible at the next process."))

    def _print_warnings(self):
        for warning in self.warnings:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("=" * 78))
            self.stdout.write(self.style.WARNING("WARNING - FABRICATED MASTER DATA"))
            self.stdout.write(self.style.WARNING("=" * 78))
            self.stdout.write(self.style.WARNING(warning))
            self.stdout.write(self.style.WARNING("=" * 78))

    def _print_summary(self):
        header = f"{'Process':<16}{'Incoming':>10}{'In progress':>13}{'Completed':>11}"
        self.stdout.write("")
        self.stdout.write(header)
        self.stdout.write("-" * len(header))
        for process in PROCESSES:
            incoming = process.incoming_queryset(None)
            in_progress = process.main_queryset(None).count()
            completed = process.complete_queryset(None).count()
            self.stdout.write(
                f"{process.label:<16}{(incoming.count() if incoming is not None else 0):>10}"
                f"{in_progress:>13}{completed:>11}"
            )

        used_types = RollingBatch.objects.values("traveller_type").distinct().count()
        active_types = TravellerType.objects.filter(is_active=True).count()
        first = RollingBatch.objects.order_by("created_at").first()
        last = RollingBatch.objects.order_by("-created_at").first()
        self.stdout.write("")
        self.stdout.write(f"Traveller types used: {used_types} / {active_types} active")
        self.stdout.write(
            f"Batches: {RollingBatch.objects.count()} "
            f"from {first.created_at.astimezone(IST):%Y-%m-%d} to {last.created_at.astimezone(IST):%Y-%m-%d}"
        )
        if used_types < active_types:
            raise CommandError(
                f"Only {used_types} of {active_types} active traveller types appear in a Rolling batch; "
                "widen the date range or raise --per-day so every type is exercised."
            )
