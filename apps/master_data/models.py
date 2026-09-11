from django.db import models

from apps.common.models import MasterDataModel


class UnitOfMeasure(MasterDataModel):
    code = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=50)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.code


class Plant(MasterDataModel):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=150)
    address = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Department(MasterDataModel):
    plant = models.ForeignKey(Plant, on_delete=models.PROTECT, related_name="departments")
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=150)

    class Meta:
        ordering = ["name"]
        unique_together = ("plant", "code")

    def __str__(self):
        return f"{self.name} ({self.plant.code})"


class Location(MasterDataModel):
    plant = models.ForeignKey(Plant, on_delete=models.PROTECT, related_name="locations")
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=150)
    location_type = models.CharField(
        max_length=20,
        choices=[("store", "Store"), ("wip", "WIP Area"), ("fg", "Finished Goods"), ("quarantine", "Quarantine")],
        default="store",
    )

    class Meta:
        ordering = ["name"]
        unique_together = ("plant", "code")

    def __str__(self):
        return self.name


class Rack(MasterDataModel):
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="racks")
    code = models.CharField(max_length=20)

    class Meta:
        ordering = ["code"]
        unique_together = ("location", "code")

    def __str__(self):
        return f"{self.location.code}-{self.code}"


class Shelf(MasterDataModel):
    rack = models.ForeignKey(Rack, on_delete=models.PROTECT, related_name="shelves")
    code = models.CharField(max_length=20)

    class Meta:
        ordering = ["code"]
        unique_together = ("rack", "code")

    def __str__(self):
        return f"{self.rack}-{self.code}"


class Tray(MasterDataModel):
    shelf = models.ForeignKey(Shelf, on_delete=models.PROTECT, related_name="trays")
    code = models.CharField(max_length=20)

    class Meta:
        ordering = ["code"]
        unique_together = ("shelf", "code")

    def __str__(self):
        return f"{self.shelf}-{self.code}"


class Machine(MasterDataModel):
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
    plant = models.ForeignKey(Plant, on_delete=models.PROTECT, related_name="machines")
    is_operational = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class Vendor(MasterDataModel):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=150)
    contact_person = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Shift(MasterDataModel):
    code = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=50)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ["start_time"]

    def __str__(self):
        return self.name


class Employee(MasterDataModel):
    employee_code = models.CharField(max_length=30, unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="employees")
    designation = models.CharField(max_length=100, blank=True)
    user = models.OneToOneField(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="employee_profile"
    )
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)

    class Meta:
        ordering = ["first_name"]

    def __str__(self):
        return f"{self.employee_code} - {self.first_name} {self.last_name}".strip()


class ProcessMaster(MasterDataModel):
    STAGE_CHOICES = [
        ("rolling", "Rolling"),
        ("forming", "Forming"),
        ("heat_treatment", "Heat Treatment"),
        ("finishing", "Finishing"),
        ("finished_goods", "Finished Goods"),
    ]
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=150)
    stage = models.CharField(max_length=20, choices=STAGE_CHOICES, db_index=True)
    sequence = models.PositiveIntegerField(default=1)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["sequence"]

    def __str__(self):
        return self.name


class ReasonCode(MasterDataModel):
    CATEGORY_CHOICES = [
        ("rejection", "Rejection"),
        ("adjustment", "Stock Adjustment"),
        ("hold", "Quality Hold"),
        ("cancellation", "Cancellation"),
    ]
    code = models.CharField(max_length=20, unique=True)
    description = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, db_index=True)

    class Meta:
        ordering = ["category", "code"]

    def __str__(self):
        return f"{self.code} - {self.description}"


class MaterialMaster(MasterDataModel):
    MATERIAL_TYPE_CHOICES = [
        ("raw_material", "Raw Material"),
        ("wip", "WIP"),
        ("consumable", "Consumable"),
    ]
    material_code = models.CharField(max_length=30, unique=True, db_index=True)
    name = models.CharField(max_length=200)
    material_type = models.CharField(max_length=20, choices=MATERIAL_TYPE_CHOICES, default="raw_material")
    unit_of_measure = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name="materials")
    grade = models.CharField(max_length=50, blank=True)
    standard_diameter_mm = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    default_vendor = models.ForeignKey(
        Vendor, on_delete=models.SET_NULL, null=True, blank=True, related_name="materials"
    )
    reorder_level = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["material_code"]

    def __str__(self):
        return f"{self.material_code} - {self.name}"


class ProductMaster(MasterDataModel):
    product_code = models.CharField(max_length=30, unique=True, db_index=True)
    name = models.CharField(max_length=200)
    unit_of_measure = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name="products")
    raw_material = models.ForeignKey(
        MaterialMaster, on_delete=models.PROTECT, related_name="products", null=True, blank=True
    )
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["product_code"]

    def __str__(self):
        return f"{self.product_code} - {self.name}"


class ProductSpecification(MasterDataModel):
    product = models.ForeignKey(ProductMaster, on_delete=models.CASCADE, related_name="specifications")
    parameter_name = models.CharField(max_length=100)
    min_value = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    max_value = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    target_value = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    unit = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["parameter_name"]

    def __str__(self):
        return f"{self.product.product_code} - {self.parameter_name}"
