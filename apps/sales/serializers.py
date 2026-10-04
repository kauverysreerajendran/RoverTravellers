from rest_framework import serializers

from apps.accounts.models import User

from . import services
from .models import (
    Activity, Lead, LeadEvent, Mill, MillContact, Notification, Reminder, SalesOrder, StockEnquiry, TrialOrder,
    Visit,
)


class UserMiniSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "full_name"]

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username


class SessionUserSerializer(UserMiniSerializer):
    app_role = serializers.SerializerMethodField()
    roles = serializers.SerializerMethodField()

    class Meta(UserMiniSerializer.Meta):
        fields = UserMiniSerializer.Meta.fields + ["email", "phone", "employee_code", "app_role", "roles"]

    def get_app_role(self, obj):
        return services.app_role(obj)

    def get_roles(self, obj):
        return sorted(obj.role_codes)


class MillContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = MillContact
        fields = ["id", "mill", "name", "designation", "phone", "email", "is_primary", "is_active"]
        read_only_fields = ["mill"]


class MillListSerializer(serializers.ModelSerializer):
    open_leads = serializers.IntegerField(read_only=True, default=0)
    visit_count = serializers.IntegerField(read_only=True, default=0)
    last_visit_date = serializers.DateField(read_only=True, default=None)
    order_count = serializers.IntegerField(read_only=True, default=0)
    journey_stage = serializers.CharField(read_only=True, default=None)
    journey_stage_label = serializers.SerializerMethodField()
    customer_status = serializers.SerializerMethodField()

    class Meta:
        model = Mill
        fields = ["id", "name", "city", "address", "gstin", "primary_contact", "contact_number", "designation",
                  "existing_traveller_used", "brand", "traveller_number", "is_active", "open_leads", "visit_count",
                  "last_visit_date", "order_count", "journey_stage", "journey_stage_label", "customer_status",
                  "created_at", "updated_at"]

    def get_journey_stage_label(self, obj):
        from .models import LEAD_STAGE_LABELS
        stage = getattr(obj, "journey_stage", None)
        return LEAD_STAGE_LABELS.get(stage) if stage else None

    def get_customer_status(self, obj):
        """Active = has ordered; Prospect = not yet; Inactive = deactivated."""
        if not obj.is_active:
            return "inactive"
        return "active" if (getattr(obj, "order_count", 0) or 0) > 0 else "prospect"


class MillSerializer(serializers.ModelSerializer):
    contacts = MillContactSerializer(many=True, read_only=True)
    created_by = UserMiniSerializer(read_only=True)

    class Meta:
        model = Mill
        fields = [
            "id", "name", "address", "city", "gstin", "primary_contact", "contact_number", "designation", "email",
            "total_spindles", "frame_details", "make", "ring_make", "ring_profile", "speed", "count", "fibre_type",
            "existing_traveller_used", "brand", "wire_section", "surface_finish", "traveller_number",
            "frequency_of_change", "sample_quantity", "remarks", "source", "erp_code", "is_active", "contacts",
            "created_by", "created_at", "updated_at",
        ]
        read_only_fields = ["source", "erp_code", "is_active"]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Mill name is required.")
        qs = Mill.objects.filter(name__iexact=value, is_active=True)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A mill with this name already exists.")
        return value

    def validate_gstin(self, value):
        value = (value or "").strip().upper()
        if value and len(value) != 15:
            raise serializers.ValidationError("GSTIN must be 15 characters.")
        return value


class LeadEventSerializer(serializers.ModelSerializer):
    stage_label = serializers.CharField(source="get_stage_display", read_only=True)
    next_action_label = serializers.CharField(source="get_next_action_display", read_only=True)
    visit_number = serializers.CharField(source="visit.number", read_only=True, default="")
    created_by = UserMiniSerializer(read_only=True)

    class Meta:
        model = LeadEvent
        fields = ["id", "stage", "stage_label", "next_action", "next_action_label", "reminder_date", "notes",
                  "visit", "visit_number", "created_by", "created_at"]


class TrialOrderSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    finish_name = serializers.CharField(source="finish.finish_name", read_only=True)
    mill_name = serializers.CharField(source="mill.name", read_only=True)
    lead_number = serializers.CharField(source="lead.number", read_only=True)
    created_by = UserMiniSerializer(read_only=True)
    reviewed_by = UserMiniSerializer(read_only=True)

    class Meta:
        model = TrialOrder
        fields = [
            "id", "number", "lead", "lead_number", "mill", "mill_name", "trial_no", "previous_trial", "product_type",
            "traveller_type", "traveller_no", "batch", "quantity", "finish", "finish_name", "trial_start_date",
            "delivery_mode", "status", "status_label", "result", "remarks", "admin_remarks", "created_by",
            "reviewed_by", "reviewed_at", "completed_at", "created_at", "updated_at",
        ]
        read_only_fields = ["number", "mill", "trial_no", "status", "result", "admin_remarks", "reviewed_at",
                            "completed_at"]


class TrialCreateSerializer(serializers.ModelSerializer):
    reminder_date = serializers.DateField(required=False, allow_null=True)

    class Meta:
        model = TrialOrder
        fields = ["lead", "previous_trial", "product_type", "traveller_type", "traveller_no", "batch", "quantity",
                  "finish", "trial_start_date", "delivery_mode", "remarks", "reminder_date"]

    def validate_delivery_mode(self, value):
        from .models import SalesMasterValue
        allowed = set(SalesMasterValue.objects.filter(category="delivery_mode", is_active=True)
                      .values_list("label", flat=True)) or {"Direct", "Courier"}
        if value not in allowed:
            raise serializers.ValidationError(f"Choose one of: {', '.join(sorted(allowed))}.")
        return value


class ReminderSerializer(serializers.ModelSerializer):
    reminder_type_label = serializers.CharField(source="get_reminder_type_display", read_only=True)
    mill_name = serializers.CharField(source="mill.name", read_only=True, default="")
    lead_number = serializers.CharField(source="lead.number", read_only=True, default="")
    assigned_to = UserMiniSerializer(read_only=True)
    created_by = UserMiniSerializer(read_only=True)
    display_status = serializers.SerializerMethodField()

    class Meta:
        model = Reminder
        fields = ["id", "reminder_type", "reminder_type_label", "entity_type", "entity_id", "mill", "mill_name",
                  "lead", "lead_number", "assigned_to", "title", "reminder_date", "default_date", "is_overridden",
                  "status", "display_status", "completed_at", "notes", "created_by", "created_at"]

    def get_display_status(self, obj):
        from django.utils import timezone
        if obj.status == "pending" and obj.reminder_date < timezone.localdate():
            return "overdue"
        return obj.status


class LeadListSerializer(serializers.ModelSerializer):
    mill_name = serializers.CharField(source="mill.name", read_only=True)
    contact_name = serializers.CharField(source="contact.name", read_only=True, default="")
    stage_label = serializers.CharField(source="get_stage_display", read_only=True)
    next_action_label = serializers.CharField(source="get_next_action_display", read_only=True)
    assigned_to = UserMiniSerializer(read_only=True)
    trial_status = serializers.SerializerMethodField()
    order_status = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = ["id", "number", "mill", "mill_name", "contact", "contact_name", "status", "stage", "stage_label",
                  "next_action", "next_action_label", "reminder_date", "stage1_step", "stage1_completed",
                  "assigned_to", "trial_status", "order_status", "visit_date", "updated_at"]

    def get_trial_status(self, obj):
        trial = obj.trials.order_by("-trial_no").first()
        return trial.get_status_display() if trial else None

    def get_order_status(self, obj):
        order = obj.orders.order_by("-created_at").first()
        return order.get_status_display() if order else None


class VisitSerializer(serializers.ModelSerializer):
    purpose_label = serializers.CharField(source="get_purpose_display", read_only=True)
    visit_type_label = serializers.CharField(source="get_visit_type_display", read_only=True)
    next_action_label = serializers.CharField(source="get_next_action_display", read_only=True)
    mill_name = serializers.CharField(source="mill.name", read_only=True)
    mill_city = serializers.CharField(source="mill.city", read_only=True)
    lead_number = serializers.CharField(source="lead.number", read_only=True)
    contact_name = serializers.CharField(source="contact.name", read_only=True, default="")
    contact_designation = serializers.CharField(source="contact.designation", read_only=True, default="")
    order_number = serializers.CharField(source="order.number", read_only=True, default="")
    trial_number = serializers.CharField(source="trial.number", read_only=True, default="")
    step_index = serializers.SerializerMethodField()
    created_by = UserMiniSerializer(read_only=True)

    class Meta:
        model = Visit
        fields = ["id", "number", "mill", "mill_name", "mill_city", "lead", "lead_number", "contact", "contact_name",
                  "contact_designation", "activity", "visit_type", "visit_type_label", "visit_date", "visit_time",
                  "purpose", "purpose_label", "step_index", "people_met", "summary", "outcome", "details",
                  "next_action", "next_action_label", "next_followup_date", "followup_overridden", "trial",
                  "trial_number", "order", "order_number", "created_by", "created_at"]

    def get_step_index(self, obj):
        from . import rules
        return rules.step_index(obj.purpose) + 1


class LeadSerializer(LeadListSerializer):
    mill_detail = MillSerializer(source="mill", read_only=True)
    contact_designation = serializers.CharField(source="contact.designation", read_only=True, default="")
    events = LeadEventSerializer(many=True, read_only=True)
    trials = TrialOrderSerializer(many=True, read_only=True)
    reminders = serializers.SerializerMethodField()
    visits = serializers.SerializerMethodField()
    journey = serializers.SerializerMethodField()
    assigned_to_id = serializers.PrimaryKeyRelatedField(
        source="assigned_to", queryset=User.objects.filter(is_active=True), required=False, allow_null=True,
        write_only=True)

    class Meta(LeadListSerializer.Meta):
        fields = LeadListSerializer.Meta.fields + [
            "mill_detail", "contact_designation", "assigned_to_id", "total_spindles", "frame_details", "make",
            "ring_make", "ring_profile", "speed", "count", "fibre_type", "existing_traveller_used", "brand",
            "wire_section", "surface_finish", "traveller_number", "frequency_of_change", "sample_quantity",
            "technical_remarks", "remarks", "closed_at", "events", "trials", "reminders", "visits", "journey",
            "created_at",
        ]
        read_only_fields = ["number", "status", "stage", "next_action", "reminder_date", "stage1_completed",
                            "closed_at"]
        extra_kwargs = {"technical_remarks": {"max_length": 500}}

    def get_reminders(self, obj):
        return ReminderSerializer(obj.reminders.order_by("-created_at")[:50], many=True).data

    def get_visits(self, obj):
        return VisitSerializer(obj.visits.select_related("mill", "lead", "contact", "order", "trial", "created_by")
                               [:50], many=True).data

    def get_journey(self, obj):
        return journey_payload(services.journey_for_mill(obj.mill, lead=obj))

    def validate(self, attrs):
        contact = attrs.get("contact")
        mill = attrs.get("mill") or (self.instance.mill if self.instance else None)
        if contact and mill and contact.mill_id != mill.pk:
            raise serializers.ValidationError({"contact": "This contact belongs to a different mill."})
        return attrs


class SalesOrderSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    order_type_label = serializers.CharField(source="get_order_type_display", read_only=True)
    mill_name = serializers.CharField(source="mill.name", read_only=True)
    traveller_type_name = serializers.CharField(source="traveller_type.name", read_only=True)
    traveller_no_code = serializers.CharField(source="traveller_no.code", read_only=True)
    finish_name = serializers.CharField(source="finish.finish_name", read_only=True)
    lead_number = serializers.CharField(source="lead.number", read_only=True, default="")
    created_by = UserMiniSerializer(read_only=True)
    reminder_date = serializers.DateField(required=False, allow_null=True, write_only=True)

    class Meta:
        model = SalesOrder
        fields = ["id", "number", "mill", "mill_name", "lead", "lead_number", "trial", "stock_enquiry",
                  "order_type", "order_type_label", "traveller_type", "traveller_type_name", "traveller_no",
                  "traveller_no_code", "finish", "finish_name", "brand", "required_m", "po_number", "po_date",
                  "order_quantity", "rate", "order_value", "delivery_date", "stock_status_at_order",
                  "status", "status_label", "remarks", "admin_remarks", "erp_reference", "created_by",
                  "created_at", "updated_at", "reminder_date"]
        read_only_fields = ["number", "status", "admin_remarks", "erp_reference", "stock_status_at_order"]


class ActivitySerializer(serializers.ModelSerializer):
    activity_type_label = serializers.CharField(source="get_activity_type_display", read_only=True)
    mill_name = serializers.CharField(source="mill.name", read_only=True)
    contact_name = serializers.CharField(source="contact.name", read_only=True, default="")
    display_status = serializers.CharField(read_only=True)
    assigned_to = UserMiniSerializer(read_only=True)
    created_by = UserMiniSerializer(read_only=True)
    assigned_to_id = serializers.PrimaryKeyRelatedField(
        source="assigned_to", queryset=User.objects.filter(is_active=True), required=False, write_only=True)

    class Meta:
        model = Activity
        fields = ["id", "number", "activity_type", "activity_type_label", "mill", "mill_name", "contact",
                  "contact_name", "lead", "date", "time", "purpose", "priority", "reminder_days_before", "notes",
                  "status", "display_status", "outcome", "assigned_to", "assigned_to_id", "created_by",
                  "completed_at", "created_at"]
        read_only_fields = ["number", "status", "outcome", "completed_at"]
        extra_kwargs = {"purpose": {"max_length": 200}, "notes": {"max_length": 300}}

    def validate(self, attrs):
        contact = attrs.get("contact")
        mill = attrs.get("mill")
        if contact and mill and contact.mill_id != mill.pk:
            raise serializers.ValidationError({"contact": "This contact belongs to a different mill."})
        if not (attrs.get("purpose") or "").strip() and not self.instance:
            raise serializers.ValidationError({"purpose": "Purpose / Objective is required."})
        return attrs


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "kind", "title", "body", "entity_type", "entity_id", "is_read", "created_at"]


class StockEnquirySerializer(serializers.ModelSerializer):
    mill_name = serializers.CharField(source="mill.name", read_only=True, default="")
    traveller_type_name = serializers.CharField(source="traveller_type.name", read_only=True)
    traveller_no_code = serializers.CharField(source="traveller_no.code", read_only=True)
    finish_name = serializers.CharField(source="finish.finish_name", read_only=True, default="")
    created_by = UserMiniSerializer(read_only=True)

    class Meta:
        model = StockEnquiry
        fields = ["id", "mill", "mill_name", "traveller_type", "traveller_type_name", "traveller_no",
                  "traveller_no_code", "finish", "finish_name", "required_m", "required_kg", "available_kg",
                  "stock_status", "is_resolved", "created_by", "created_at"]


def journey_payload(journey):
    lead = journey["lead"]
    return {
        "lead": LeadListSerializer(lead).data if lead is not None else None,
        "steps": journey["steps"],
        "current": journey["current"],
        "allowed_steps": journey["allowed_steps"],
        "suggested_next": journey["suggested_next"],
    }
