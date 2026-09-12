import re
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.common.models import MasterDataModel

# ---------------------------------------------------------------------------
# Independent master tables. Every dropdown/auto-populate field on the
# process forms (Rolling, and later Forming/Heat Treatment/Finishing) is
# driven from these tables, never hardcoded in a template or JS array.
# ---------------------------------------------------------------------------


class TravellerType(models.Model):
    """68 official traveller types (see Traveller Type Master PDF)."""

    traveller_type_id = models.AutoField(primary_key=True)
    seq_no = models.PositiveIntegerField(unique=True, help_text="Row number in the official master list (1-68).")
    # Not unique: the official 68-row master list itself repeats "RE2 UDR"
    # at rows 17 and 63, so seq_no (not name) is the true business key.
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["seq_no"]
        indexes = [models.Index(fields=["name"])]

    def __str__(self):
        return self.name


class TravellerNo(models.Model):
    """Traveller numbers are bare codes ('1'/'0'). `label` is retained for
    future business meaning but is never shown: rendering it produced
    "1 (Pending label)" everywhere the traveller number appears."""

    traveller_no_id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=5, unique=True)
    label = models.CharField(max_length=50, blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.code


class SurfaceFinish(models.Model):
    finish_id = models.AutoField(primary_key=True)
    finish_name = models.CharField(max_length=50, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["finish_name"]

    def __str__(self):
        return self.finish_name


class RackMaster(models.Model):
    rack_id = models.AutoField(primary_key=True)
    rack_code = models.CharField(max_length=20, unique=True)
    capacity = models.PositiveIntegerField(default=10, help_text="Number of coil slots on this rack.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["rack_code"]

    def __str__(self):
        return self.rack_code


class DiameterMaster(models.Model):
    """Raw material managed by diameter. total_stock / active_coils are
    kept as denormalized counters recalculated from CoilMaster on every
    receipt/consumption, per the stock calculation rule in the spec."""

    raw_material_id = models.CharField(max_length=10, primary_key=True, help_text="e.g. RM-093")
    diameter_mm = models.DecimalField(max_digits=6, decimal_places=2, unique=True)
    unit = models.CharField(max_length=10, default="KG")
    total_stock = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    active_coils = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=10, choices=[("Active", "Active"), ("Inactive", "Inactive")], default="Active"
    )

    class Meta:
        ordering = ["diameter_mm"]
        indexes = [models.Index(fields=["diameter_mm"])]

    def __str__(self):
        return f"{self.raw_material_id} ({self.diameter_mm} mm)"

    def recalculate_stock(self):
        active = self.coils.filter(status="In Stock")
        self.total_stock = active.aggregate(total=models.Sum("weight_kg"))["total"] or Decimal("0")
        self.active_coils = active.count()
        self.save(update_fields=["total_stock", "active_coils"])

    @staticmethod
    def generate_raw_material_id(diameter_mm: Decimal) -> str:
        return f"RM-{int(round(diameter_mm * 100)):03d}"


class CoilMaster(models.Model):
    """Child of DiameterMaster. Coil numbering restarts at 1 for a diameter
    only once every coil under it has been fully consumed."""

    STATUS_CHOICES = [("In Stock", "In Stock"), ("Consumed", "Consumed")]

    coil_id = models.AutoField(primary_key=True)
    coil_display_number = models.PositiveIntegerField()
    raw_material = models.ForeignKey(DiameterMaster, on_delete=models.PROTECT, related_name="coils")
    weight_kg = models.DecimalField(max_digits=8, decimal_places=2)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="In Stock")
    rack = models.ForeignKey(RackMaster, on_delete=models.SET_NULL, null=True, blank=True, related_name="coils")
    supplier = models.CharField(max_length=100, blank=True)
    received_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["raw_material", "coil_display_number"]
        indexes = [models.Index(fields=["raw_material", "status"])]

    def __str__(self):
        return f"Coil {self.coil_display_number} ({self.raw_material_id})"

    def clean(self):
        if self.weight_kg is not None and self.weight_kg < 0:
            raise ValidationError("Coil weight cannot be negative.")

    @staticmethod
    def next_display_number(raw_material: DiameterMaster) -> int:
        """If any active (In Stock) coils exist for this diameter, continue
        the sequence; otherwise restart from 1."""
        active_max = CoilMaster.objects.filter(raw_material=raw_material, status="In Stock").aggregate(
            m=models.Max("coil_display_number")
        )["m"]
        if active_max:
            return active_max + 1
        return 1


class DiameterTravellerMapping(models.Model):
    """One raw-material diameter (+ F-Thickness/F-Width) per traveller type.
    Drives the Wire Diameter / F-Thickness / F-Width auto-populate on the
    Rolling form once a Traveller Type is selected."""

    mapping_id = models.AutoField(primary_key=True)
    traveller_type = models.OneToOneField(TravellerType, on_delete=models.CASCADE, related_name="mapping")
    raw_material = models.ForeignKey(DiameterMaster, on_delete=models.PROTECT, related_name="traveller_mappings")
    f_thickness_mm = models.DecimalField(max_digits=5, decimal_places=2)
    f_width_mm = models.DecimalField(max_digits=5, decimal_places=2)

    def __str__(self):
        return f"{self.traveller_type.name} -> {self.raw_material_id}"


class WireSerialMaster(models.Model):
    """Every wire serial pre-loaded as master data: SA01-SA1000, then
    SB01-SB1000, then SC01-SC1000. Rolling consumes them strictly in
    order, so the "next serial" is simply the first Available row by
    sort_order rather than a number computed at runtime."""

    STATUS_CHOICES = [("Available", "Available"), ("Used", "Used")]

    serial_id = models.AutoField(primary_key=True)
    serial_no = models.CharField(max_length=10, unique=True, db_index=True)
    prefix = models.CharField(max_length=2, db_index=True)
    sequence = models.PositiveIntegerField(help_text="1-1000 within the prefix block.")
    sort_order = models.PositiveIntegerField(unique=True, help_text="Global issue order across all prefixes.")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="Available", db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["sort_order"]
        indexes = [models.Index(fields=["status", "sort_order"])]
        verbose_name = "Wire Serial"
        verbose_name_plural = "Wire Serials"

    def __str__(self):
        return self.serial_no

    @staticmethod
    def format_serial(prefix: str, sequence: int) -> str:
        """SA01 / SB110 / SA1000 - minimum two digits, no truncation."""
        return f"{prefix}{sequence:02d}"


class Machine(MasterDataModel):
    """Production machines. Moved here from `master_data` so it sits with
    the other master tables (see masters.0005/0006 - the move is state-only
    plus a table rename, so no row data is touched)."""

    STAGE_CHOICES = [
        ("rolling", "Rolling"),
        ("forming", "Forming"),
        ("heat_treatment", "Heat Treatment"),
        ("finishing", "Finishing"),
        ("general", "General"),
    ]
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=150)
    stage = models.CharField(max_length=20, choices=STAGE_CHOICES, default="general")
    plant = models.ForeignKey("master_data.Plant", on_delete=models.PROTECT, related_name="machines")
    is_operational = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        """Machines are identified by their code alone ("1A"); rendering
        code + name produced "1A - forming 1A" in every dropdown."""
        return self.code


# ---------------------------------------------------------------------------
# Storage rack zones - the physical grids material sits on between
# processes. `RackMaster` above is the raw-material coil bay and is
# untouched by these tables: a zone belongs to a *process*, and the
# process whose completion (or receipt) puts material on it is named by
# `process_slug`, resolved against the process registry rather than any
# hardcoded list of stages.
# ---------------------------------------------------------------------------

ROW_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def row_letter(row: int) -> str:
    """1 -> A, 2 -> B. Beyond Z the number itself is used, so an oversized
    grid degrades to a readable label instead of raising."""
    index = row - 1
    return ROW_LETTERS[index] if 0 <= index < len(ROW_LETTERS) else str(row)


class RackZone(models.Model):
    """One storage area: N identical racks of `rows` x `columns` slots.

    `process_slug` is the process that places material here - Rolling's
    completed wire waits on the Forming zone, received stock sits on the
    Finished Goods zone. It is validated against the registry at save
    time so a zone can never point at a process that does not exist.
    """

    zone_id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=10, unique=True, help_text="e.g. FORMING, FG")
    name = models.CharField(max_length=100)
    process_slug = models.CharField(
        max_length=30, db_index=True,
        help_text="Slug of the process whose completion/receipt places material on this zone.",
    )
    rack_count = models.PositiveIntegerField(default=1)
    rows = models.PositiveIntegerField(default=5)
    columns = models.PositiveIntegerField(default=5)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Rack Zone"

    def __str__(self):
        return self.name

    # ------------------------------------------------------------------
    def clean(self):
        from apps.production.process_registry import process_sequence

        slugs = process_sequence()
        if self.process_slug not in slugs:
            raise ValidationError(
                {"process_slug": f'"{self.process_slug}" is not a process. Expected one of: {", ".join(slugs)}.'}
            )
        if not self.rows or not self.columns:
            raise ValidationError("A zone needs at least one row and one column of slots.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    @property
    def slots_per_rack(self):
        return self.rows * self.columns

    @property
    def total_slots(self):
        return self.rack_count * self.slots_per_rack

    @property
    def process(self):
        from apps.production.process_registry import get_process

        return get_process(self.process_slug)


class StorageRack(models.Model):
    """One physical rack inside a zone (FR-01 ... FR-10)."""

    rack_id = models.AutoField(primary_key=True)
    zone = models.ForeignKey(RackZone, on_delete=models.CASCADE, related_name="racks")
    code = models.CharField(max_length=20)
    position = models.PositiveIntegerField(help_text="1-based position of this rack within its zone.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["zone", "position"]
        constraints = [
            models.UniqueConstraint(fields=["zone", "code"], name="unique_zone_rack_code"),
            models.UniqueConstraint(fields=["zone", "position"], name="unique_zone_rack_position"),
        ]

    def __str__(self):
        return self.code

    def clean(self):
        if self.position and self.zone_id and self.position > self.zone.rack_count:
            raise ValidationError({
                "position": (
                    f"{self.zone.name} holds {self.zone.rack_count} racks; "
                    f"position {self.position} is outside it."
                )
            })

    def save(self, *args, **kwargs):
        creating = self._state.adding
        super().save(*args, **kwargs)
        if creating:
            self.build_slots()

    def build_slots(self):
        """Every slot exists as a real row from the moment the rack does, so
        an empty slot is a record the screens read rather than a gap the
        template has to invent."""
        existing = set(self.slots.values_list("row", "column"))
        missing = [
            RackSlot(rack=self, zone_id=self.zone_id, row=row, column=column)
            for row in range(1, self.zone.rows + 1)
            for column in range(1, self.zone.columns + 1)
            if (row, column) not in existing
        ]
        if missing:
            RackSlot.objects.bulk_create(missing)
        return len(missing)


class RackSlot(models.Model):
    """One addressable position on a rack, holding at most one lot.

    `zone` is denormalized from `rack.zone` purely so the database itself
    can enforce "a lot occupies at most one slot per zone"; it is always
    written from the rack and never set independently.
    """

    slot_id = models.AutoField(primary_key=True)
    rack = models.ForeignKey(StorageRack, on_delete=models.CASCADE, related_name="slots")
    zone = models.ForeignKey(RackZone, on_delete=models.CASCADE, related_name="slots", editable=False)
    row = models.PositiveIntegerField()
    column = models.PositiveIntegerField()

    lot = models.ForeignKey(
        "production.ProductionLot", on_delete=models.SET_NULL, null=True, blank=True, related_name="rack_slots"
    )
    placed_at = models.DateTimeField(null=True, blank=True)
    placed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["rack__position", "row", "column"]
        constraints = [
            models.UniqueConstraint(fields=["rack", "row", "column"], name="unique_rack_slot_position"),
            models.UniqueConstraint(
                fields=["zone", "lot"], condition=models.Q(lot__isnull=False), name="unique_zone_lot_slot"
            ),
        ]
        indexes = [models.Index(fields=["zone", "lot"])]

    def __str__(self):
        return self.label

    def save(self, *args, **kwargs):
        if self.rack_id and self.zone_id != self.rack.zone_id:
            self.zone_id = self.rack.zone_id
        super().save(*args, **kwargs)

    @property
    def label(self):
        return f"{self.rack.code}-{row_letter(self.row)}{self.column}"

    @property
    def is_empty(self):
        return self.lot_id is None


class RackPlacement(models.Model):
    """History of what has sat where. One open row (released_at IS NULL)
    per occupied slot; closed rows keep a slot's past traceable after the
    material has moved on."""

    placement_id = models.AutoField(primary_key=True)
    slot = models.ForeignKey(RackSlot, on_delete=models.CASCADE, related_name="placements")
    lot = models.ForeignKey("production.ProductionLot", on_delete=models.CASCADE, related_name="rack_placements")
    placed_at = models.DateTimeField()
    released_at = models.DateTimeField(null=True, blank=True)
    placed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    released_reason = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["-placed_at"]
        indexes = [models.Index(fields=["lot", "released_at"])]

    def __str__(self):
        state = "released" if self.released_at else "on rack"
        return f"{self.lot_id} @ {self.slot.label} ({state})"


class BatchNoFormat(models.Model):
    """How a process numbers its batches, as data rather than code.

    Heat Treatment groups its transactions into a Heat Batch numbered
    B001, B002 ...; the pattern, its prefix and its width live here so the
    business can change them without a deployment, and so nothing in the
    code has to spell a batch number out.
    """

    format_id = models.AutoField(primary_key=True)
    process_slug = models.CharField(
        max_length=30, db_index=True, help_text="Slug of the process whose batches this format numbers."
    )
    regex = models.CharField(max_length=100, help_text=r"Full-match pattern, e.g. ^B\d{3}$")
    prefix = models.CharField(max_length=10, blank=True, default="", help_text="e.g. B")
    pad = models.PositiveSmallIntegerField(default=3, help_text="Digits after the prefix.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["process_slug"]
        verbose_name = "Batch No Format"

    def __str__(self):
        return f"{self.process_slug}: {self.regex}"

    def clean(self):
        from apps.production.process_registry import process_sequence

        slugs = process_sequence()
        if self.process_slug not in slugs:
            raise ValidationError(
                {"process_slug": f'"{self.process_slug}" is not a process. Expected one of: {", ".join(slugs)}.'}
            )
        try:
            re.compile(self.regex)
        except re.error as exc:
            raise ValidationError({"regex": f"Not a valid pattern: {exc}"})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    # ------------------------------------------------------------------
    @classmethod
    def for_process(cls, process):
        """The active format for a process (or its slug), or None."""
        if process is None:
            return None
        slug = getattr(process, "slug", process)
        return cls.objects.filter(process_slug=slug, is_active=True).first()

    def normalize(self, batch_no: str) -> str:
        """Batch numbers are written by hand on the shop floor, so "b001"
        and " B001 " are the same batch."""
        return (batch_no or "").strip().upper()

    def matches(self, batch_no: str) -> bool:
        return bool(re.fullmatch(self.regex, self.normalize(batch_no)))

    def format_number(self, number: int) -> str:
        return f"{self.prefix}{number:0{self.pad}d}"

    def number_of(self, batch_no: str):
        """The numeric part of a batch number, or None if it has none."""
        digits = re.sub(r"\D", "", self.normalize(batch_no) or "")
        return int(digits) if digits else None
