"""Web-side view of the sales data (same tables the mobile app writes)."""
from django.contrib import admin

from .models import (
    Activity, Lead, LeadEvent, Mill, MillContact, Notification, Reminder, SalesMasterValue, SalesOrder,
    StockEnquiry, TrialOrder, Visit,
)


class ReadOnlyAuditMixin:
    readonly_fields = ("created_at", "updated_at", "created_by", "updated_by")


@admin.register(SalesMasterValue)
class SalesMasterValueAdmin(admin.ModelAdmin):
    list_display = ("category", "label", "code", "sort_order", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("label", "code")
    list_editable = ("sort_order", "is_active")


class MillContactInline(admin.TabularInline):
    model = MillContact
    extra = 0
    fields = ("name", "designation", "phone", "email", "is_primary", "is_active")


@admin.register(Mill)
class MillAdmin(ReadOnlyAuditMixin, admin.ModelAdmin):
    list_display = ("name", "city", "gstin", "primary_contact", "contact_number", "source", "is_active", "updated_at")
    list_filter = ("is_active", "source", "fibre_type", "ring_profile")
    search_fields = ("name", "city", "gstin", "primary_contact", "contacts__name")
    inlines = [MillContactInline]


class LeadEventInline(admin.TabularInline):
    model = LeadEvent
    extra = 0
    can_delete = False
    readonly_fields = ("stage", "next_action", "reminder_date", "notes", "visit", "created_by", "created_at")


class TrialInline(admin.TabularInline):
    model = TrialOrder
    extra = 0
    can_delete = False
    fk_name = "lead"
    fields = ("number", "trial_no", "product_type", "batch", "quantity", "finish", "trial_start_date", "status")
    readonly_fields = fields


@admin.register(Lead)
class LeadAdmin(ReadOnlyAuditMixin, admin.ModelAdmin):
    list_display = ("number", "mill", "contact", "stage", "next_action", "reminder_date", "status", "assigned_to",
                    "updated_at")
    list_filter = ("status", "stage", "assigned_to")
    search_fields = ("number", "mill__name", "contact__name")
    readonly_fields = ReadOnlyAuditMixin.readonly_fields + ("number",)
    inlines = [LeadEventInline, TrialInline]


@admin.register(TrialOrder)
class TrialOrderAdmin(ReadOnlyAuditMixin, admin.ModelAdmin):
    list_display = ("number", "trial_no", "mill", "lead", "product_type", "batch", "quantity", "finish",
                    "trial_start_date", "delivery_mode", "status", "created_by")
    list_filter = ("status", "delivery_mode", "finish")
    search_fields = ("number", "mill__name", "lead__number", "product_type", "batch")
    readonly_fields = ReadOnlyAuditMixin.readonly_fields + ("number", "trial_no")


@admin.register(SalesOrder)
class SalesOrderAdmin(ReadOnlyAuditMixin, admin.ModelAdmin):
    list_display = ("number", "mill", "po_number", "traveller_type", "traveller_no", "finish", "order_quantity", "required_m", "order_type",
                    "status", "created_by", "created_at")
    list_filter = ("status", "order_type", "finish")
    search_fields = ("number", "mill__name", "traveller_type__name", "traveller_no__code")
    readonly_fields = ReadOnlyAuditMixin.readonly_fields + ("number",)


@admin.register(Activity)
class ActivityAdmin(ReadOnlyAuditMixin, admin.ModelAdmin):
    list_display = ("number", "activity_type", "mill", "date", "time", "purpose", "priority", "status",
                    "assigned_to", "created_by")
    list_filter = ("status", "activity_type", "priority", "assigned_to")
    search_fields = ("number", "mill__name", "purpose")
    readonly_fields = ReadOnlyAuditMixin.readonly_fields + ("number",)


@admin.register(Reminder)
class ReminderAdmin(ReadOnlyAuditMixin, admin.ModelAdmin):
    list_display = ("reminder_type", "title", "mill", "assigned_to", "reminder_date", "default_date",
                    "is_overridden", "status", "completed_at")
    list_filter = ("status", "reminder_type", "is_overridden", "assigned_to")
    search_fields = ("title", "mill__name", "entity_id")


@admin.register(StockEnquiry)
class StockEnquiryAdmin(ReadOnlyAuditMixin, admin.ModelAdmin):
    list_display = ("created_at", "mill", "traveller_type", "traveller_no", "finish", "required_m",
                    "available_kg", "stock_status", "is_resolved", "created_by")
    list_filter = ("stock_status", "is_resolved")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("created_at", "recipient", "kind", "title", "is_read")
    list_filter = ("kind", "is_read", "recipient")


@admin.register(Visit)
class VisitAdmin(ReadOnlyAuditMixin, admin.ModelAdmin):
    list_display = ("number", "visit_date", "mill", "purpose", "visit_type", "next_action", "next_followup_date",
                    "order", "trial", "created_by")
    list_filter = ("purpose", "visit_type", "created_by")
    search_fields = ("number", "mill__name", "summary", "people_met")
    readonly_fields = ReadOnlyAuditMixin.readonly_fields + ("number",)
    date_hierarchy = "visit_date"
