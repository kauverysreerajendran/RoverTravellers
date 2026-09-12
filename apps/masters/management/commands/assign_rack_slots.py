"""Put material that is already in the database onto its rack slot.

The storage zones arrived after the process history did, so every batch
Rolling had already completed - and every Finished Goods row already
received - is on a rack in reality but on no slot in the database. This
command walks each active zone and places that material, oldest first,
through the same `place_lot` service the screens use.

What belongs on a zone is read from the registry, never from a stage
name: a zone's process is `RackZone.process_slug`, and the material
waiting on it is exactly what the *following* process shows as incoming
(for the terminal process, every row it holds). `place_lot` is
idempotent, so a second run places nothing and reports it.
"""

from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError

from apps.masters import services as rack_services
from apps.masters.models import RackZone


class Command(BaseCommand):
    help = "Place existing material on the storage rack zones (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--zone", default="", help="Only this zone code (default: every active zone)."
        )

    def handle(self, *args, **options):
        zones = RackZone.objects.filter(is_active=True).order_by("code")
        if options["zone"]:
            zones = zones.filter(code=options["zone"])
            if not zones.exists():
                raise CommandError(f'No active rack zone with code "{options["zone"]}".')

        for zone in zones:
            self._assign(zone)

    # ------------------------------------------------------------------
    def _assign(self, zone):
        process = zone.process
        if process is None:
            raise CommandError(
                f"{zone.name} points at process \"{zone.process_slug}\", which is not in the registry."
            )

        records = self._waiting_records(process)
        placed = already = skipped = 0
        for record in records:
            lot = record.handover_lot
            if lot is None:
                skipped += 1
                continue
            if rack_services.slot_for_lot(zone, lot) is not None:
                already += 1
                continue
            try:
                slot = rack_services.place_lot(zone, lot, None)
            except ValidationError as exc:
                raise CommandError(
                    f"{zone.name} ran out of space after placing {placed} of {len(records)}: "
                    f"{'; '.join(exc.messages)}. Add racks to the zone, or free slots, and run again."
                )
            placed += 1
            self.stdout.write(f"  {slot.label}  <-  {record.wire_serial or lot.lot_number}")

        summary = rack_services.zone_summary(zone)
        self.stdout.write(self.style.SUCCESS(
            f"{zone.name}: {placed} placed, {already} already on a slot"
            + (f", {skipped} without a traceable lot" if skipped else "")
            + f" | {summary['occupied']} / {summary['total_slots']} slots occupied"
        ))

    @staticmethod
    def _waiting_records(process):
        """The records whose material is sitting on this process's zone,
        oldest first: what the next process has not picked up yet, or -
        for the terminal process, which nothing follows - everything it
        holds."""
        following = process.next
        if following is not None:
            records = list(following.incoming_queryset(None))
        else:
            records = list(process.base_queryset())
        return sorted(records, key=lambda r: (r.completed_at is None, r.completed_at))
