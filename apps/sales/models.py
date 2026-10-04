"""Sales & Marketing domain for the Rover mobile app and web admin.

Everything here lives in the one central Rover database, next to the
production masters it reuses (TravellerType, TravellerNo, SurfaceFinish).
The mobile app never keeps its own copy of any of these tables: it reads
and writes them through the /api/sales/ endpoints.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import MasterDataModel, TimeStampedModel, generate_business_number
from apps.masters.models import SurfaceFinish, TravellerNo, TravellerType

# ---------------------------------------------------------------------------
# Vocabulary. Codes are stored; labels are what both apps display.
# ---------------------------------------------------------------------------

# The Sales Journey (reference: "Sales Journey at a Glance"). Every visit /
# call is recorded against one of these ten steps; a lead's `stage` is the
# latest step recorded. Not every customer goes through every step.
JOURNEY_STEPS = [
    ("initial_introduction", "Initial Introduction"),
    ("requirement_discussion", "Requirement Discussion"),
    ("sample_requested", "Sample Requested"),
    ("sample_delivered", "Sample Delivered"),
    ("trial", "Trial"),
    ("trial_followup", "Trial Follow-up"),
    ("order_discussion", "Order Discussion"),
    ("order_received", "Order Received"),
    ("repeat_order_followup", "Repeat Order Follow-up"),
    ("repeat_order", "Repeat Order"),
]
JOURNEY_CODES = [c for c, _ in JOURNEY_STEPS]

LEAD_STAGES = JOURNEY_STEPS + [("no_further_action", "No Further Action")]
LEAD_STAGE_LABELS = dict(LEAD_STAGES)

# What can be chosen as "Next Action": revisit at the same step, any journey
# step, or close the lead.
NEXT_ACTIONS = [("followup", "Follow-up Call/Visit")] + LEAD_STAGES
NEXT_ACTION_LABELS = dict(NEXT_ACTIONS)

VISIT_TYPES = [
    ("mill_visit", "Mill Visit"),
    ("phone_call", "Phone Call"),
    ("online_meeting", "Online Meeting"),
    ("office_visit", "Office Visit"),
]

LEAD_STATUS = [("draft", "Draft"), ("open", "Open"), ("closed", "Closed")]

TRIAL_STATUSES = [
    ("trial_created", "Trial Created"),
    ("trial_pending", "Trial Pending"),
    ("trial_in_progress", "Trial In Progress"),
    ("trial_successful", "Trial Successful"),
    ("trial_failed", "Trial Failed"),
    ("repeat_trial", "Repeat Trial"),
    ("order_followup", "Order Follow-up"),
    ("order_placed", "Order Placed"),
]

ORDER_STATUSES = [
    ("draft", "Draft"),
    ("placed", "Placed"),
    ("under_review", "Under Review"),
    ("confirmed", "Confirmed"),
    ("processing", "Processing"),
    ("dispatched", "Dispatched"),
    ("completed", "Completed"),
    ("cancelled", "Cancelled"),
]

ORDER_TYPES = [
    ("stock", "From Stock"),
    ("new_requirement", "New Requirement (Rolling)"),
    ("repeat", "Repeat Order"),
]

ACTIVITY_TYPES = [
    ("visit", "Visit"),
    ("call", "Call"),
    ("followup", "Follow-up"),
    ("meeting", "Meeting"),
    ("other", "Other"),
]
ACTIVITY_STATUS = [("pending", "Pending"), ("completed", "Completed"), ("cancelled", "Cancelled")]
PRIORITIES = [("low", "Low"), ("normal", "Normal"), ("high", "High")]

REMINDER_TYPES = [
    ("lead_followup", "Lead Follow-up"),
    ("sample_followup", "Sample Follow-up"),
    ("trial_followup", "Trial Follow-up"),
    ("repeat_trial", "Repeat Trial"),
    ("order_followup", "Order Follow-up"),
    ("repeat_order", "Repeat Order"),
    ("activity", "Activity"),
]
REMINDER_STATUS = [
    ("pending", "Pending"),
    ("completed", "Completed"),
    ("cancelled", "Cancelled"),
    # Replaced by a newer reminder for the same entity. Kept for history.
    ("superseded", "Superseded"),
]

MASTER_CATEGORIES = [
    ("brand", "Brand"),
    ("make", "Machine Make"),
    ("ring_make", "Ring Make"),
    ("ring_profile", "Ring Profile"),
    ("fibre_type", "Fibre Type"),
    ("delivery_mode", "Delivery Mode"),
    ("frequency", "Frequency of Change"),
    ("existing_traveller", "Existing Traveller Used"),
    ("designation", "Designation"),
]

SOURCE_CHOICES = [("manual", "Manual"), ("erp", "ERP"), ("demo", "Development seed")]


class SalesMasterValue(models.Model):
    """One centralized lookup table for the small sales masters (Brand, Ring
    Make, Ring Profile, Fibre Type, Delivery Mode ...). Maintained in the web
    admin; the mobile app only reads it."""

    category = models.CharField(max_length=30, choices=MASTER_CATEGORIES, db_index=True)
    code = models.CharField(max_length=50)
    label = models.CharField(max_length=100)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category", "sort_order", "label"]
        constraints = [models.UniqueConstraint(fields=["category", "code"], name="uniq_sales_master_value")]

    def __str__(self):
        return f"{self.get_category_display()}: {self.label}"


class Mill(MasterDataModel):
    """The central Mill / Customer master."""

    name = models.CharField(max_length=200, db_index=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    gstin = models.CharField("GSTIN", max_length=20, blank=True, db_index=True)
    primary_contact = models.CharField(max_length=120, blank=True)
    contact_number = models.CharField(max_length=20, blank=True)
    designation = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)

    # Mill & machine profile (latest known values, updated from visits).
    total_spindles = models.PositiveIntegerField(null=True, blank=True)
    frame_details = models.CharField(max_length=200, blank=True)
    make = models.CharField(max_length=100, blank=True)
    ring_make = models.CharField(max_length=100, blank=True)
    ring_profile = models.CharField(max_length=20, blank=True)
    speed = models.CharField(max_length=50, blank=True)
    count = models.CharField(max_length=50, blank=True)
    fibre_type = models.CharField(max_length=30, blank=True)

    # Traveller currently used at the mill.
    existing_traveller_used = models.CharField(max_length=100, blank=True)
    brand = models.CharField(max_length=100, blank=True)
    wire_section = models.CharField("Type / Wire Section", max_length=100, blank=True)
    surface_finish = models.CharField(max_length=100, blank=True)
    traveller_number = models.CharField(max_length=50, blank=True)
    frequency_of_change = models.CharField(max_length=100, blank=True)
    sample_quantity = models.CharField(max_length=100, blank=True)
    remarks = models.TextField(blank=True)

    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="manual")
    erp_code = models.CharField(max_length=50, blank=True, db_index=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class MillContact(TimeStampedModel):
    mill = models.ForeignKey(Mill, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=120)
    designation = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    is_primary = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-is_primary", "name"]

    def __str__(self):
        return f"{self.name} ({self.mill})"


class Lead(TimeStampedModel):
    number = models.CharField(max_length=30, unique=True, editable=False, db_index=True)
    mill = models.ForeignKey(Mill, on_delete=models.PROTECT, related_name="leads")
    contact = models.ForeignKey(MillContact, null=True, blank=True, on_delete=models.SET_NULL, related_name="leads")
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="sales_leads"
    )
    status = models.CharField(max_length=10, choices=LEAD_STATUS, default="draft", db_index=True)
    stage = models.CharField(max_length=30, choices=LEAD_STAGES, default="initial_introduction", db_index=True)
    next_action = models.CharField(max_length=30, choices=NEXT_ACTIONS, blank=True)
    reminder_date = models.DateField(null=True, blank=True)

    # Stage 1 - Mill Visit & Initial Assessment (screens 1-4).
    stage1_step = models.PositiveSmallIntegerField(default=1, help_text="Last saved wizard screen (1-4).")
    stage1_completed = models.BooleanField(default=False)
    visit_date = models.DateField(null=True, blank=True)
    total_spindles = models.PositiveIntegerField(null=True, blank=True)
    frame_details = models.CharField(max_length=200, blank=True)
    make = models.CharField(max_length=100, blank=True)
    ring_make = models.CharField(max_length=100, blank=True)
    ring_profile = models.CharField(max_length=20, blank=True)
    speed = models.CharField(max_length=50, blank=True)
    count = models.CharField(max_length=50, blank=True)
    fibre_type = models.CharField(max_length=30, blank=True)
    existing_traveller_used = models.CharField(max_length=100, blank=True)
    brand = models.CharField(max_length=100, blank=True)
    wire_section = models.CharField(max_length=100, blank=True)
    surface_finish = models.CharField(max_length=100, blank=True)
    traveller_number = models.CharField(max_length=50, blank=True)
    frequency_of_change = models.CharField(max_length=100, blank=True)
    sample_quantity = models.CharField(max_length=100, blank=True)
    technical_remarks = models.CharField(max_length=500, blank=True)
    remarks = models.TextField(blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = generate_business_number("LD", Lead, "number")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.number} - {self.mill}"


class LeadEvent(models.Model):
    """Immutable timeline row: every journey step recorded on a lead."""

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="events")
    stage = models.CharField(max_length=30, choices=LEAD_STAGES)
    next_action = models.CharField(max_length=30, choices=NEXT_ACTIONS, blank=True)
    visit = models.ForeignKey("Visit", null=True, blank=True, on_delete=models.SET_NULL, related_name="events")
    reminder_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]


class TrialOrder(TimeStampedModel):
    number = models.CharField(max_length=30, unique=True, editable=False, db_index=True)
    lead = models.ForeignKey(Lead, on_delete=models.PROTECT, related_name="trials")
    mill = models.ForeignKey(Mill, on_delete=models.PROTECT, related_name="trials")
    trial_no = models.PositiveIntegerField(help_text="1, 2, 3 ... per lead. Never reused.")
    previous_trial = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name="repeats")
    product_type = models.CharField(max_length=120)
    traveller_type = models.ForeignKey(TravellerType, null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")
    traveller_no = models.ForeignKey(TravellerNo, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    batch = models.CharField(max_length=50)
    quantity = models.CharField(max_length=50)
    finish = models.ForeignKey(SurfaceFinish, on_delete=models.PROTECT, related_name="+")
    trial_start_date = models.DateField()
    delivery_mode = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=TRIAL_STATUSES, default="trial_created", db_index=True)
    result = models.CharField(max_length=20, blank=True)
    remarks = models.TextField(blank=True)
    admin_remarks = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["lead", "trial_no"], name="uniq_trial_no_per_lead")]

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = generate_business_number("TR", TrialOrder, "number")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.number} (Trial {self.trial_no})"


class StockEnquiry(TimeStampedModel):
    """Every stock check made from the sales app, so enquiries that never
    became an order are visible to Admin ("Pending Stock Enquiries")."""

    mill = models.ForeignKey(Mill, null=True, blank=True, on_delete=models.SET_NULL, related_name="stock_enquiries")
    traveller_type = models.ForeignKey(TravellerType, on_delete=models.PROTECT, related_name="+")
    traveller_no = models.ForeignKey(TravellerNo, on_delete=models.PROTECT, related_name="+")
    finish = models.ForeignKey(SurfaceFinish, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    required_m = models.DecimalField(max_digits=14, decimal_places=2)
    required_kg = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    available_kg = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    stock_status = models.CharField(max_length=25)
    is_resolved = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class SalesOrder(TimeStampedModel):
    number = models.CharField(max_length=30, unique=True, editable=False, db_index=True)
    mill = models.ForeignKey(Mill, on_delete=models.PROTECT, related_name="orders")
    lead = models.ForeignKey(Lead, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")
    trial = models.ForeignKey(TrialOrder, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")
    stock_enquiry = models.ForeignKey(StockEnquiry, null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name="orders")
    order_type = models.CharField(max_length=20, choices=ORDER_TYPES, default="stock")
    traveller_type = models.ForeignKey(TravellerType, on_delete=models.PROTECT, related_name="+")
    traveller_no = models.ForeignKey(TravellerNo, on_delete=models.PROTECT, related_name="+")
    finish = models.ForeignKey(SurfaceFinish, on_delete=models.PROTECT, related_name="+")
    brand = models.CharField(max_length=100, blank=True)
    required_m = models.DecimalField("Required M", max_digits=14, decimal_places=2, null=True, blank=True)
    # Purchase order details (Order Received / Repeat Order visit, or Create Order).
    po_number = models.CharField("PO Number", max_length=60, blank=True, db_index=True)
    po_date = models.DateField("PO Date", null=True, blank=True)
    order_quantity = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True,
                                         help_text="Pieces")
    rate = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="Rs per piece")
    order_value = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    delivery_date = models.DateField(null=True, blank=True)
    stock_status_at_order = models.CharField(max_length=25, blank=True)
    status = models.CharField(max_length=20, choices=ORDER_STATUSES, default="placed", db_index=True)
    remarks = models.TextField(blank=True)
    admin_remarks = models.TextField(blank=True)
    erp_reference = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = generate_business_number("SO", SalesOrder, "number")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.number


class Activity(TimeStampedModel):
    number = models.CharField(max_length=30, unique=True, editable=False, db_index=True)
    activity_type = models.CharField(max_length=20, choices=ACTIVITY_TYPES)
    mill = models.ForeignKey(Mill, on_delete=models.PROTECT, related_name="activities")
    contact = models.ForeignKey(MillContact, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    lead = models.ForeignKey(Lead, null=True, blank=True, on_delete=models.SET_NULL, related_name="activities")
    date = models.DateField(db_index=True)
    # Optional by business rule: Prathap plans by the day, not by the clock.
    time = models.TimeField(null=True, blank=True)
    purpose = models.CharField(max_length=200)
    priority = models.CharField(max_length=10, choices=PRIORITIES, default="normal")
    reminder_days_before = models.PositiveSmallIntegerField(null=True, blank=True)
    notes = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=10, choices=ACTIVITY_STATUS, default="pending", db_index=True)
    outcome = models.TextField(blank=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                    related_name="sales_activities")
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["date", "time"]

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = generate_business_number("ACT", Activity, "number")
        super().save(*args, **kwargs)

    @property
    def display_status(self):
        if self.status == "pending" and self.date < timezone.localdate():
            return "overdue"
        return self.status

    def __str__(self):
        return f"{self.number} {self.get_activity_type_display()} - {self.mill}"


class Reminder(TimeStampedModel):
    reminder_type = models.CharField(max_length=20, choices=REMINDER_TYPES, db_index=True)
    entity_type = models.CharField(max_length=30, db_index=True)
    entity_id = models.CharField(max_length=64, db_index=True)
    mill = models.ForeignKey(Mill, null=True, blank=True, on_delete=models.SET_NULL, related_name="reminders")
    lead = models.ForeignKey(Lead, null=True, blank=True, on_delete=models.SET_NULL, related_name="reminders")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="sales_reminders")
    title = models.CharField(max_length=200, blank=True)
    reminder_date = models.DateField(db_index=True)
    default_date = models.DateField(null=True, blank=True, help_text="What the default rule computed.")
    is_overridden = models.BooleanField(default=False)
    status = models.CharField(max_length=12, choices=REMINDER_STATUS, default="pending", db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    notified_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["reminder_date", "created_at"]

    def __str__(self):
        return f"{self.get_reminder_type_display()} {self.reminder_date}"


class Visit(TimeStampedModel):
    """One visit / call recorded against a Sales Journey step ("Visit
    Recording"). Step-specific answers live in `details`; orders and trials it
    produces are linked so every step can be traced end to end."""

    number = models.CharField(max_length=30, unique=True, editable=False, db_index=True)
    mill = models.ForeignKey(Mill, on_delete=models.PROTECT, related_name="visits")
    lead = models.ForeignKey(Lead, on_delete=models.PROTECT, related_name="visits")
    contact = models.ForeignKey(MillContact, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    activity = models.ForeignKey(Activity, null=True, blank=True, on_delete=models.SET_NULL, related_name="visits")
    visit_type = models.CharField(max_length=20, choices=VISIT_TYPES, default="mill_visit")
    visit_date = models.DateField(db_index=True)
    visit_time = models.TimeField(null=True, blank=True)
    purpose = models.CharField("Purpose of Visit", max_length=30, choices=JOURNEY_STEPS, db_index=True)
    people_met = models.CharField(max_length=300, blank=True)
    summary = models.TextField("Discussion Summary / Remarks", blank=True)
    outcome = models.CharField(max_length=60, blank=True)
    details = models.JSONField(default=dict, blank=True)
    next_action = models.CharField(max_length=30, choices=NEXT_ACTIONS)
    next_followup_date = models.DateField(null=True, blank=True)
    followup_overridden = models.BooleanField(default=False)
    trial = models.ForeignKey(TrialOrder, null=True, blank=True, on_delete=models.SET_NULL, related_name="visits")
    order = models.ForeignKey(SalesOrder, null=True, blank=True, on_delete=models.SET_NULL, related_name="visits")

    class Meta:
        ordering = ["-visit_date", "-visit_time", "-created_at"]

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = generate_business_number("VS", Visit, "number")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.number} {self.get_purpose_display()} - {self.mill}"


class Notification(models.Model):
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                  related_name="sales_notifications")
    kind = models.CharField(max_length=30)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    entity_type = models.CharField(max_length=30, blank=True)
    entity_id = models.CharField(max_length=64, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title
