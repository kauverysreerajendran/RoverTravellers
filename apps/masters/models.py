from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

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
    """Placeholder labels ('1'/'0') pending real business meaning — kept
    DB-driven so a label correction is a data update, not a code change."""

    traveller_no_id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=5, unique=True)
    label = models.CharField(max_length=50, blank=True, default="Pending label")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} ({self.label})" if self.label else self.code


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
