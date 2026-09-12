"""Put material on a process's incoming list, through the real services.

A process's Main Table only shows what is waiting there, so to try a screen
that works on several lots at once - the Heat Treatment batch screen, say -
there has to be several lots waiting. This walks new material from the
origin process up to the one named and stops, leaving it on that process's
incoming list ready to be initiated.

Every step goes through the same service an operator's screen calls, so
the wire serials, coil consumption, WIP, rack slots, audit trail and
handover chain are exactly what they would be if the work had been done by
hand. Which processes exist and what order they run in comes from the
registry; the only slug is the one you pass in.

    python manage.py stage_incoming_work --to heat_treatment --count 22
"""

import datetime
from decimal import ROUND_HALF_UP, Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.masters import services as masters_services
from apps.masters.models import CoilMaster, DiameterTravellerMapping, Machine, RackMaster, TravellerNo
from apps.production import services as production_services
from apps.production.process_registry import PROCESSES, get_process
from apps.rolling import services as rolling_services

# A lot's weight, and how much of it survives each process.
LOT_WEIGHT = (Decimal("40.00"), Decimal("95.00"))
YIELD = Decimal("0.975")
# Coils are received when stock runs short, so a long run does not stop
# half way for want of raw material.
COIL_WEIGHT = Decimal("400.00")


def money(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class Command(BaseCommand):
    help = "Walk new material to a process and leave it on that process's incoming list."

    def add_arguments(self, parser):
        parser.add_argument("--to", required=True, help="Process slug to leave the material waiting at.")
        parser.add_argument("--count", type=int, default=20, help="How many lots to stage (default 20).")
        parser.add_argument(
            "--user", default="", help="Username to record the work against (default: the first superuser).",
        )

    def handle(self, *args, **options):
        target = get_process(options["to"])
        if target is None:
            raise CommandError(
                f'"{options["to"]}" is not a process. Expected one of: '
                + ", ".join(process.slug for process in PROCESSES)
            )
        if target.previous is None:
            raise CommandError(
                f"{target.label} is the origin process: nothing is handed to it, so nothing can wait there."
            )

        user = self._user(options["user"])
        mappings = list(
            DiameterTravellerMapping.objects.select_related("traveller_type", "raw_material")
            .filter(traveller_type__is_active=True)
        )
        if not mappings:
            raise CommandError("No traveller type has a raw material mapping; nothing can be rolled.")
        traveller_no = TravellerNo.objects.filter(is_active=True).first()
        if traveller_no is None:
            raise CommandError("No traveller numbers in the master.")

        before = target.incoming_queryset(None).count()
        staged = []
        for index in range(options["count"]):
            mapping = mappings[index % len(mappings)]
            with transaction.atomic():
                staged.append(self._stage_one(target, mapping, traveller_no, user, index))

        after = target.incoming_queryset(None).count()
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"{len(staged)} lots walked to {target.label}: "
            f"incoming there went from {before} to {after}."
        ))
        types = {serial_type for _, serial_type in staged}
        self.stdout.write(f"   traveller types staged: {len(types)} ({', '.join(sorted(types)[:6])}"
                          f"{' ...' if len(types) > 6 else ''})")

    # ------------------------------------------------------------------
    def _user(self, username):
        from apps.accounts.models import User

        user = (
            User.objects.filter(username=username).first()
            if username else User.objects.filter(is_superuser=True).order_by("pk").first()
        )
        if user is None:
            raise CommandError("No user to record this work against.")
        return user

    def _stage_one(self, target, mapping, traveller_no, user, index):
        """One lot: rolled, then walked forward until it is waiting at the
        target process."""
        weight = money(LOT_WEIGHT[0] + (LOT_WEIGHT[1] - LOT_WEIGHT[0]) * Decimal(index % 7) / Decimal(7))
        coil = self._coil_for(mapping.raw_material, weight, user)

        origin = PROCESSES[0]
        record = rolling_services.initiate_rolling_batch(
            traveller_type=mapping.traveller_type,
            traveller_no=traveller_no,
            finish=self._finish(),
            required_box=1 + index % 5,
            wire_weight_issued_kg=weight,
            coil_weights=[(coil.coil_id, weight)],
            user=user,
        )
        serial = record.wire_serial
        output = money(weight * YIELD)
        rolling_services.complete_rolling_batch(
            record,
            rolled_thickness_mm=record.f_thickness_mm,
            rolled_width_mm=record.f_width_mm,
            finished_weight_kg=output,
            user=user,
        )

        # Walk it forward, stopping at the process it should wait at.
        for step in range(1, target.index):
            process = PROCESSES[step]
            lot = record.handover_lot if step == 1 else record.lot
            record = production_services.initiate_stage(
                process, lot, user, **self._initiate_fields(process)
            )
            output = money(output * YIELD)
            record.output_quantity = output
            record.save(update_fields=["output_quantity"])
            production_services.complete_stage(record, user)
            record.refresh_from_db()

        self.stdout.write(f"   {serial:<8} {mapping.traveller_type.name:<24} {output} kg -> {target.label}")
        return serial, mapping.traveller_type.name

    def _initiate_fields(self, process):
        fields = {}
        names = {field.name for field in process.model._meta.get_fields()}
        if "operation_date" in names:
            fields["operation_date"] = timezone.localdate()
        if "machine" in names:
            machine = Machine.objects.filter(stage=process.slug, is_operational=True).first()
            if machine is not None:
                fields["machine"] = machine
        return fields

    def _coil_for(self, raw_material, weight, user):
        """A coil of this diameter with enough wire on it, receiving one
        through the real service when stock is short."""
        coil = (
            CoilMaster.objects.filter(raw_material=raw_material, status="In Stock", weight_kg__gte=weight)
            .order_by("coil_display_number")
            .first()
        )
        if coil is not None:
            return coil
        return masters_services.receive_coil(
            raw_material=raw_material,
            weight_kg=COIL_WEIGHT,
            rack=RackMaster.objects.filter(is_active=True).order_by("rack_code").first(),
            supplier="Staged for demo",
            received_date=datetime.date.today(),
        )

    @staticmethod
    def _finish():
        from apps.masters.models import SurfaceFinish

        finish = SurfaceFinish.objects.filter(is_active=True).first()
        if finish is None:
            raise CommandError("No surface finishes in the master.")
        return finish
