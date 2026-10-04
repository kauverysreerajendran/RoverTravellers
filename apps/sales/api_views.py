from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Max, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.authentication import SessionAuthentication
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.audit.models import AuditLog, log_action
from apps.masters.models import SurfaceFinish, TravellerNo, TravellerType

from . import rules, services
from .authentication import ExpiringTokenAuthentication, token_ttl

# Token first so an expired/invalid token answers 401 (the app then shows
# "Session expired"); the web session still works on the same endpoints.
SALES_AUTH = [ExpiringTokenAuthentication, SessionAuthentication]
from .models import (
    ACTIVITY_TYPES, JOURNEY_STEPS, LEAD_STAGES, NEXT_ACTIONS, ORDER_STATUSES, PRIORITIES, REMINDER_TYPES,
    TRIAL_STATUSES, VISIT_TYPES, Activity, Lead, LeadEvent, Mill, MillContact, Notification, Reminder,
    SalesMasterValue, SalesOrder, StockEnquiry, TrialOrder, Visit,
)
from .permissions import IsSalesAdmin, IsSalesUser
from .serializers import (
    ActivitySerializer, LeadListSerializer, LeadSerializer, MillContactSerializer, MillListSerializer,
    MillSerializer, NotificationSerializer, ReminderSerializer, SalesOrderSerializer, SessionUserSerializer,
    StockEnquirySerializer, TrialCreateSerializer, TrialOrderSerializer, UserMiniSerializer, VisitSerializer,
    journey_payload,
)


def _raise(exc):
    """Django validation/permission errors -> DRF responses."""
    if isinstance(exc, DjangoPermissionDenied):
        raise PermissionDenied(str(exc))
    if hasattr(exc, "error_dict"):
        raise ValidationError({k: [str(m) for m in v] for k, v in exc.message_dict.items()})
    raise ValidationError({"detail": exc.messages})


def _date_param(request, name):
    raw = request.data.get(name) if hasattr(request, "data") else None
    if raw in (None, ""):
        return None
    value = parse_date(str(raw))
    if value is None:
        raise ValidationError({name: "Use YYYY-MM-DD."})
    return value


class SalesViewMixin:
    authentication_classes = SALES_AUTH
    permission_classes = [IsSalesUser]

    @property
    def is_admin(self):
        return services.is_sales_admin(self.request.user)


# ---------------------------------------------------------------------------
# Auth (same users and passwords as the web app)
# ---------------------------------------------------------------------------

class LoginView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        username = (request.data.get("username") or "").strip()
        password = request.data.get("password") or ""
        if not username or not password:
            return Response({"detail": "Enter username and password."}, status=status.HTTP_400_BAD_REQUEST)
        # Usernames are matched case-insensitively ("prathap" == "Prathap") so a
        # phone keyboard's auto-capitalisation does not lock the user out.
        match = User.objects.filter(username__iexact=username).first()
        user = authenticate(request, username=match.username if match else username, password=password)
        if user is None:
            return Response({"detail": "Invalid username or password."}, status=status.HTTP_401_UNAUTHORIZED)
        if not services.is_sales_user(user):
            return Response({"detail": "This account does not have access to the Sales app."},
                            status=status.HTTP_403_FORBIDDEN)
        Token.objects.filter(user=user).delete()
        token = Token.objects.create(user=user)
        log_action(user, "login", user, description="Sales mobile login")
        return Response({
            "token": token.key,
            "expires_at": token.created + token_ttl(),
            "user": SessionUserSerializer(user).data,
        })


class LogoutView(APIView):
    authentication_classes = SALES_AUTH
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        log_action(request.user, "logout", request.user, description="Sales mobile logout")
        return Response({"detail": "Logged out."})


class MeView(APIView):
    authentication_classes = SALES_AUTH
    permission_classes = [IsSalesUser]

    def get(self, request):
        return Response(SessionUserSerializer(request.user).data)


# ---------------------------------------------------------------------------
# Masters
# ---------------------------------------------------------------------------

class MastersView(APIView):
    authentication_classes = SALES_AUTH
    permission_classes = [IsSalesUser]

    def get(self, request):
        values = {}
        for row in SalesMasterValue.objects.filter(is_active=True):
            values.setdefault(row.category, []).append({"code": row.code, "label": row.label})
        return Response({
            "values": values,
            "traveller_types": list(TravellerType.objects.filter(is_active=True).order_by("seq_no")
                                    .values("traveller_type_id", "seq_no", "name")),
            "traveller_numbers": list(TravellerNo.objects.filter(is_active=True).values("traveller_no_id", "code")),
            "finishes": list(SurfaceFinish.objects.filter(is_active=True).order_by("finish_name")
                             .values("finish_id", "finish_name")),
            "lead_stages": [{"code": c, "label": l} for c, l in LEAD_STAGES],
            "journey_steps": [{"code": c, "label": l} for c, l in JOURNEY_STEPS],
            "next_actions": [{"code": c, "label": l} for c, l in NEXT_ACTIONS],
            "next_actions_by_step": {c: rules.next_actions(c) for c in rules.JOURNEY},
            "allowed_steps_by_step": {c: rules.allowed_steps(c) for c in rules.JOURNEY},
            "suggested_next": rules.SUGGESTED_NEXT,
            "stage1_next_actions": [{"code": c, "label": l} for c, l in NEXT_ACTIONS if c in rules.STAGE1_NEXT_ACTIONS],
            "visit_types": [{"code": c, "label": l} for c, l in VISIT_TYPES],
            "trial_statuses": [{"code": c, "label": l} for c, l in TRIAL_STATUSES],
            "trial_transitions": rules.TRIAL_TRANSITIONS,
            "order_statuses": [{"code": c, "label": l} for c, l in ORDER_STATUSES],
            "order_transitions": rules.ORDER_TRANSITIONS,
            "activity_types": [{"code": c, "label": l} for c, l in ACTIVITY_TYPES],
            "priorities": [{"code": c, "label": l} for c, l in PRIORITIES],
            "reminder_types": [{"code": c, "label": l} for c, l in REMINDER_TYPES],
            "default_reminder_days": rules.reminder_days(),
            "brand": getattr(settings, "SALES_OWN_BRAND", "Rover"),
        })


class SalesUsersView(APIView):
    authentication_classes = SALES_AUTH
    permission_classes = [IsSalesUser]

    def get(self, request):
        users = (services.sales_executives() | services.sales_admins()).distinct().order_by("username")
        data = []
        for u in users:
            row = UserMiniSerializer(u).data
            row["app_role"] = services.app_role(u)
            data.append(row)
        return Response(data)


# ---------------------------------------------------------------------------
# Mills / customers (the central master)
# ---------------------------------------------------------------------------

class MillViewSet(SalesViewMixin, viewsets.ModelViewSet):
    search_fields = ["name", "city", "gstin", "primary_contact", "contact_number", "contacts__name",
                     "traveller_number", "existing_traveller_used"]
    ordering_fields = ["name", "updated_at"]

    def get_queryset(self):
        params = self.request.query_params
        status_filter = params.get("status")
        include_inactive = (params.get("include_inactive") or status_filter in ("inactive", "all")) and \
            (self.is_admin or status_filter in ("inactive", "all"))
        qs = Mill.objects.all() if include_inactive else Mill.objects.filter(is_active=True)
        latest_lead = Lead.objects.filter(mill=OuterRef("pk")).order_by(services.models_case_open_first(),
                                                                        "-updated_at")
        qs = qs.annotate(
            open_leads=Count("leads", filter=Q(leads__status="open"), distinct=True),
            visit_count=Count("visits", distinct=True),
            last_visit_date=Max("visits__visit_date"),
            order_count=Count("orders", filter=~Q(orders__status="cancelled"), distinct=True),
            journey_stage=Subquery(latest_lead.values("stage")[:1]),
        )
        if status_filter == "active":
            qs = qs.filter(is_active=True, order_count__gt=0)
        elif status_filter == "prospect":
            qs = qs.filter(is_active=True, order_count=0)
        elif status_filter == "inactive":
            qs = qs.filter(is_active=False)
        if params.get("stage"):
            qs = qs.filter(journey_stage=params["stage"])
        sort = params.get("sort")
        if sort == "last_visited":
            from django.db.models import F
            qs = qs.order_by(F("last_visit_date").desc(nulls_last=True), "name")
        elif sort == "newest":
            qs = qs.order_by("-created_at")
        else:
            qs = qs.order_by("name")
        return qs.prefetch_related("contacts")

    def get_serializer_class(self):
        return MillListSerializer if self.action == "list" else MillSerializer

    def perform_create(self, serializer):
        mill = serializer.save(created_by=self.request.user, updated_by=self.request.user)
        # The primary contact becomes a contact row so it is selectable in leads/activities.
        if mill.primary_contact:
            MillContact.objects.create(mill=mill, name=mill.primary_contact, designation=mill.designation,
                                       phone=mill.contact_number, is_primary=True, created_by=self.request.user)
        log_action(self.request.user, "create", mill, description=f"Mill {mill.name} created")
        services.notify_admins(exclude=self.request.user, kind="mill_created", title=f"New customer: {mill.name}",
                               body=mill.city, entity=mill)

    def perform_update(self, serializer):
        mill = serializer.save(updated_by=self.request.user)
        log_action(self.request.user, "update", mill, description=f"Mill {mill.name} updated",
                   metadata={"fields": sorted(serializer.validated_data.keys())})

    def destroy(self, request, *args, **kwargs):
        if not self.is_admin:
            raise PermissionDenied("Only Admin can deactivate a mill.")
        mill = self.get_object()
        mill.is_active = False
        mill.updated_by = request.user
        mill.save()
        log_action(request.user, "cancel", mill, description=f"Mill {mill.name} deactivated")
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get", "post"])
    def contacts(self, request, pk=None):
        mill = self.get_object()
        if request.method == "POST":
            serializer = MillContactSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            contact = serializer.save(mill=mill, created_by=request.user, updated_by=request.user)
            log_action(request.user, "create", contact, description=f"Contact {contact.name} added to {mill.name}")
            return Response(MillContactSerializer(contact).data, status=status.HTTP_201_CREATED)
        return Response(MillContactSerializer(mill.contacts.filter(is_active=True), many=True).data)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        today = timezone.localdate()
        month_start = today.replace(day=1)
        mills = Mill.objects.filter(is_active=True).annotate(
            oc=Count("orders", filter=~Q(orders__status="cancelled"), distinct=True))
        return Response({
            "total": mills.count(),
            "active": mills.filter(oc__gt=0).count(),
            "prospects": mills.filter(oc=0).count(),
            "inactive": Mill.objects.filter(is_active=False).count(),
            "visited_this_month": mills.filter(visits__visit_date__gte=month_start).distinct().count(),
            "new_this_month": mills.filter(created_at__date__gte=month_start).count(),
        })

    @action(detail=True, methods=["get"])
    def journey(self, request, pk=None):
        mill = self.get_object()
        journey = journey_payload(services.journey_for_mill(mill))
        visits = Visit.objects.filter(mill=mill).select_related("mill", "lead", "contact", "order", "trial",
                                                                "created_by")
        journey["visits"] = VisitSerializer(visits[:100], many=True).data
        journey["mill"] = MillListSerializer(self.get_queryset().get(pk=mill.pk)).data
        return Response(journey)

    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        mill = self.get_object()
        leads = Lead.objects.filter(mill=mill)
        orders = SalesOrder.objects.filter(mill=mill)
        trials = TrialOrder.objects.filter(mill=mill)
        activities = Activity.objects.filter(mill=mill)
        if not self.is_admin:
            leads = leads.filter(assigned_to=request.user)
        return Response({
            "mill": MillSerializer(mill).data,
            "leads": LeadListSerializer(leads.select_related("mill", "contact", "assigned_to")[:20], many=True).data,
            "trials": TrialOrderSerializer(trials.select_related("finish", "mill", "lead")[:20], many=True).data,
            "orders": SalesOrderSerializer(orders.select_related("traveller_type", "traveller_no", "finish",
                                                                 "mill")[:20], many=True).data,
            "activities": ActivitySerializer(activities.select_related("mill", "contact").order_by("-date")[:20],
                                             many=True).data,
            "visits": VisitSerializer(Visit.objects.filter(mill=mill).select_related(
                "mill", "lead", "contact", "order", "trial", "created_by")[:20], many=True).data,
            "journey": journey_payload(services.journey_for_mill(mill)),
        })


class MillContactViewSet(SalesViewMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                         viewsets.GenericViewSet):
    queryset = MillContact.objects.all()
    serializer_class = MillContactSerializer

    def perform_update(self, serializer):
        contact = serializer.save(updated_by=self.request.user)
        log_action(self.request.user, "update", contact, description=f"Contact {contact.name} updated")


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------

LEAD_FILTERS = {
    "all": Q(),
    "draft": Q(status="draft"),
    "open": Q(status="open"),
    "followup": Q(status="open", stage__in=["initial_introduction", "requirement_discussion"]),
    "sample": Q(status="open", stage__in=["sample_requested", "sample_delivered"]),
    "trial": Q(status="open", stage__in=["trial", "trial_followup"]),
    "order_followup": Q(status="open", stage="order_discussion"),
    "order_placed": Q(status="open", stage__in=["order_received", "repeat_order_followup", "repeat_order"]),
    "closed": Q(status="closed"),
}


class LeadViewSet(SalesViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                  viewsets.GenericViewSet):
    search_fields = ["number", "mill__name", "contact__name", "traveller_number", "wire_section",
                     "existing_traveller_used"]
    ordering_fields = ["updated_at", "reminder_date", "created_at"]

    def get_queryset(self):
        qs = Lead.objects.select_related("mill", "contact", "assigned_to").prefetch_related("trials", "orders")
        if not self.is_admin:
            qs = qs.filter(assigned_to=self.request.user)
        params = self.request.query_params
        key = params.get("filter", "all")
        if key not in LEAD_FILTERS:
            raise ValidationError({"filter": f"Use one of {', '.join(LEAD_FILTERS)}."})
        qs = qs.filter(LEAD_FILTERS[key])
        if params.get("mill"):
            qs = qs.filter(mill_id=params["mill"])
        if params.get("assigned_to") and self.is_admin:
            qs = qs.filter(assigned_to_id=params["assigned_to"])
        if params.get("stage"):
            qs = qs.filter(stage=params["stage"])
        return qs

    def get_serializer_class(self):
        return LeadListSerializer if self.action == "list" else LeadSerializer

    def perform_create(self, serializer):
        user = self.request.user
        assigned = serializer.validated_data.get("assigned_to") if self.is_admin else None
        stage1_step = max(1, min(int(self.request.data.get("step") or 1), 4))
        lead = serializer.save(assigned_to=assigned or user, created_by=user, updated_by=user,
                               stage1_step=stage1_step)
        log_action(user, "create", lead, description=f"Lead {lead.number} created for {lead.mill.name}",
                   metadata={"assigned_to": lead.assigned_to.username})
        if lead.assigned_to_id != user.pk:
            services.notify([lead.assigned_to], kind="lead_assigned", title=f"Lead {lead.number} assigned",
                            body=lead.mill.name, entity=lead)

    @action(detail=True, methods=["post"])
    def stage1(self, request, pk=None):
        """Save one Stage-1 screen. `validate=true` (the Next button) also
        checks that screen's required fields; Save alone keeps a draft."""
        lead = self.get_object()
        if lead.stage1_completed:
            raise ValidationError({"detail": "Stage 1 is already complete for this lead."})
        try:
            step = int(request.data.get("step") or lead.stage1_step)
        except (TypeError, ValueError):
            raise ValidationError({"step": "Step must be 1-4."})
        if step not in (1, 2, 3, 4):
            raise ValidationError({"step": "Step must be 1-4."})
        payload = {k: v for k, v in request.data.items()
                   if k in services.STAGE1_FIELDS or k in ("mill", "contact")}
        serializer = LeadSerializer(lead, data=payload, partial=True)
        serializer.is_valid(raise_exception=True)
        lead = serializer.save(updated_by=request.user, stage1_step=max(lead.stage1_step, step))
        if str(request.data.get("validate", "")).lower() in ("1", "true", "yes"):
            errors = services.validate_stage1_step(lead, step)
            if errors:
                return Response({"errors": errors, "lead": LeadSerializer(lead).data},
                                status=status.HTTP_400_BAD_REQUEST)
            if step < 4:
                lead.stage1_step = max(lead.stage1_step, step + 1)
                lead.save(update_fields=["stage1_step", "updated_at"])
        return Response(LeadSerializer(lead).data)

    @action(detail=True, methods=["post"], url_path="complete-stage1")
    def complete_stage1(self, request, pk=None):
        lead = self.get_object()
        try:
            lead = services.complete_stage1(lead, request.user, request.data.get("next_action") or "",
                                            reminder_override=_date_param(request, "reminder_date"),
                                            notes=request.data.get("notes") or "")
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            _raise(exc)
        return Response(LeadSerializer(lead).data)

    @action(detail=True, methods=["post"])
    def advance(self, request, pk=None):
        lead = self.get_object()
        try:
            lead = services.advance_lead(lead, request.user, request.data.get("next_action") or "",
                                         reminder_override=_date_param(request, "reminder_date"),
                                         notes=request.data.get("notes") or "",
                                         step=request.data.get("step") or None)
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            _raise(exc)
        return Response(LeadSerializer(lead).data)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        if not self.is_admin:
            raise PermissionDenied("Only Admin can reassign leads.")
        lead = self.get_object()
        user = get_object_or_404(User, pk=request.data.get("assigned_to"), is_active=True)
        old = lead.assigned_to
        lead.assigned_to = user
        lead.updated_by = request.user
        lead.save()
        Reminder.objects.filter(lead=lead, status="pending").update(assigned_to=user)
        log_action(request.user, "update", lead, description="Lead reassigned",
                   metadata={"from": old.username if old else None, "to": user.username})
        services.notify([user], kind="lead_assigned", title=f"Lead {lead.number} assigned", body=lead.mill.name,
                        entity=lead)
        return Response(LeadSerializer(lead).data)

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        lead = self.get_object()
        entity_ids = [str(lead.pk)] + [str(t.pk) for t in lead.trials.all()] + [str(o.pk) for o in lead.orders.all()]
        logs = AuditLog.objects.filter(entity_id__in=entity_ids).select_related("user")[:200]
        return Response([{
            "action": log.action, "entity_type": log.entity_type, "description": log.description,
            "metadata": log.metadata, "user": log.user.username if log.user else None, "created_at": log.created_at,
        } for log in logs])


# ---------------------------------------------------------------------------
# Trials
# ---------------------------------------------------------------------------

class TrialViewSet(SalesViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = TrialOrderSerializer
    search_fields = ["number", "mill__name", "product_type", "batch", "lead__number"]
    ordering_fields = ["created_at", "trial_start_date"]

    def get_queryset(self):
        qs = TrialOrder.objects.select_related("mill", "lead", "finish", "created_by", "reviewed_by")
        if not self.is_admin:
            qs = qs.filter(Q(lead__assigned_to=self.request.user) | Q(created_by=self.request.user))
        params = self.request.query_params
        if params.get("status"):
            qs = qs.filter(status__in=params["status"].split(","))
        if params.get("lead"):
            qs = qs.filter(lead_id=params["lead"])
        if params.get("mill"):
            qs = qs.filter(mill_id=params["mill"])
        return qs.distinct()

    def create(self, request):
        serializer = TrialCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        lead = data["lead"]
        if not self.is_admin and lead.assigned_to_id != request.user.pk:
            raise PermissionDenied("This lead is not assigned to you.")
        try:
            trial = services.create_trial(
                lead=lead, user=request.user, product_type=data["product_type"], batch=data["batch"],
                quantity=data["quantity"], finish=data["finish"], trial_start_date=data["trial_start_date"],
                delivery_mode=data["delivery_mode"], remarks=data.get("remarks", ""),
                traveller_type=data.get("traveller_type"), traveller_no=data.get("traveller_no"),
                previous_trial=data.get("previous_trial"), reminder_override=data.get("reminder_date"),
            )
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            _raise(exc)
        return Response(TrialOrderSerializer(trial).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="set-status")
    def set_status(self, request, pk=None):
        trial = self.get_object()
        try:
            trial = services.set_trial_status(trial, request.user, request.data.get("status") or "",
                                              result=request.data.get("result") or "",
                                              remarks=request.data.get("remarks") or "",
                                              reminder_override=_date_param(request, "reminder_date"))
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            _raise(exc)
        return Response(TrialOrderSerializer(trial).data)


# ---------------------------------------------------------------------------
# Stock + orders
# ---------------------------------------------------------------------------

class StockCheckView(APIView):
    authentication_classes = SALES_AUTH
    permission_classes = [IsSalesUser]

    def post(self, request):
        mill = None
        if request.data.get("mill"):
            mill = Mill.objects.filter(pk=request.data["mill"]).first()
        try:
            result = services.check_stock(
                traveller_type_id=request.data.get("traveller_type_id"),
                traveller_no_id=request.data.get("traveller_no_id"),
                finish_id=request.data.get("finish_id"), required_m=request.data.get("required_m"),
                mill=mill, user=request.user,
            )
        except DjangoValidationError as exc:
            _raise(exc)
        return Response(result)


class StockCheckOptionsView(APIView):
    """Stock Check dropdowns: only what is in Finished Goods right now."""
    authentication_classes = SALES_AUTH
    permission_classes = [IsSalesUser]

    def get(self, request):
        return Response({"results": services.stock_check_options()})


class StockEnquiryViewSet(SalesViewMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = StockEnquirySerializer

    def get_queryset(self):
        qs = StockEnquiry.objects.select_related("mill", "traveller_type", "traveller_no", "finish", "created_by")
        if not self.is_admin:
            qs = qs.filter(created_by=self.request.user)
        if self.request.query_params.get("pending"):
            qs = qs.filter(is_resolved=False).exclude(stock_status="IN_STOCK")
        return qs


class SalesOrderViewSet(SalesViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                        viewsets.GenericViewSet):
    serializer_class = SalesOrderSerializer
    search_fields = ["number", "mill__name", "traveller_type__name", "traveller_no__code", "lead__number"]
    ordering_fields = ["created_at"]

    def get_queryset(self):
        qs = SalesOrder.objects.select_related("mill", "lead", "traveller_type", "traveller_no", "finish",
                                               "created_by")
        if not self.is_admin:
            qs = qs.filter(Q(created_by=self.request.user) | Q(lead__assigned_to=self.request.user))
        params = self.request.query_params
        if params.get("status"):
            qs = qs.filter(status__in=params["status"].split(","))
        if params.get("mill"):
            qs = qs.filter(mill_id=params["mill"])
        if params.get("lead"):
            qs = qs.filter(lead_id=params["lead"])
        if params.get("order_type"):
            qs = qs.filter(order_type=params["order_type"])
        return qs.distinct()

    def create(self, request):
        serializer = SalesOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        lead = data.get("lead")
        if lead is not None and not self.is_admin and lead.assigned_to_id != request.user.pk:
            raise PermissionDenied("This lead is not assigned to you.")
        try:
            order = services.create_order(
                user=request.user, mill=data["mill"], traveller_type=data["traveller_type"],
                traveller_no=data["traveller_no"], finish=data["finish"], required_m=data.get("required_m"),
                order_type=data.get("order_type") or None, brand=data.get("brand", ""),
                remarks=data.get("remarks", ""), lead=lead, trial=data.get("trial"),
                stock_enquiry=data.get("stock_enquiry"), reminder_override=data.get("reminder_date"),
                po_number=data.get("po_number", ""), po_date=data.get("po_date"),
                order_quantity=data.get("order_quantity"), rate=data.get("rate"),
                order_value=data.get("order_value"), delivery_date=data.get("delivery_date"),
            )
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            _raise(exc)
        return Response(SalesOrderSerializer(order).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="set-status")
    def set_status(self, request, pk=None):
        order = self.get_object()
        try:
            order = services.set_order_status(order, request.user, request.data.get("status") or "",
                                              remarks=request.data.get("remarks") or "")
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            _raise(exc)
        return Response(SalesOrderSerializer(order).data)


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------

class ActivityViewSet(SalesViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                      mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = ActivitySerializer
    search_fields = ["number", "mill__name", "purpose", "contact__name"]

    def get_queryset(self):
        qs = Activity.objects.select_related("mill", "contact", "assigned_to", "created_by")
        if not self.is_admin:
            qs = qs.filter(assigned_to=self.request.user)
        params = self.request.query_params
        today = timezone.localdate()
        bucket = params.get("bucket")
        if bucket == "today":
            qs = qs.filter(date=today).exclude(status="cancelled")
        elif bucket == "upcoming":
            qs = qs.filter(date__gt=today, status="pending")
        elif bucket == "overdue":
            qs = qs.filter(date__lt=today, status="pending")
        elif bucket == "completed":
            qs = qs.filter(status="completed").order_by("-date")
        elif bucket == "pending":
            qs = qs.filter(status="pending")
        if params.get("assigned_to") and self.is_admin:
            qs = qs.filter(assigned_to_id=params["assigned_to"])
        if params.get("mill"):
            qs = qs.filter(mill_id=params["mill"])
        return qs

    def create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        assigned_to = data.pop("assigned_to", None)
        try:
            activity = services.create_activity(user=request.user, assigned_to=assigned_to, **data)
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            _raise(exc)
        return Response(ActivitySerializer(activity).data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        if serializer.instance.status != "pending":
            raise ValidationError({"detail": "Only a pending activity can be edited."})
        if "assigned_to" in serializer.validated_data and not self.is_admin:
            raise PermissionDenied("Only Admin can reassign activities.")
        activity = serializer.save(updated_by=self.request.user)
        log_action(self.request.user, "update", activity, description="Activity updated")

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        return self._status(request, "completed")

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._status(request, "cancelled")

    def _status(self, request, new_status):
        activity = self.get_object()
        try:
            activity = services.set_activity_status(activity, request.user, new_status,
                                                    outcome=request.data.get("outcome") or "")
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            _raise(exc)
        return Response(ActivitySerializer(activity).data)


# ---------------------------------------------------------------------------
# Visit Recording (Sales Journey)
# ---------------------------------------------------------------------------

class VisitViewSet(SalesViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = VisitSerializer
    search_fields = ["number", "mill__name", "summary", "people_met", "contact__name"]

    def get_queryset(self):
        qs = Visit.objects.select_related("mill", "lead", "contact", "order", "trial", "created_by")
        if not self.is_admin:
            qs = qs.filter(Q(created_by=self.request.user) | Q(lead__assigned_to=self.request.user))
        params = self.request.query_params
        for key, field in (("mill", "mill_id"), ("lead", "lead_id"), ("purpose", "purpose"),
                           ("visit_type", "visit_type")):
            if params.get(key):
                qs = qs.filter(**{field: params[key]})
        if params.get("date"):
            qs = qs.filter(visit_date=parse_date(params["date"]))
        if params.get("date_from"):
            qs = qs.filter(visit_date__gte=parse_date(params["date_from"]))
        if params.get("date_to"):
            qs = qs.filter(visit_date__lte=parse_date(params["date_to"]))
        if params.get("created_by") and self.is_admin:
            qs = qs.filter(created_by_id=params["created_by"])
        return qs.distinct()

    def create(self, request):
        data = request.data
        mill = Mill.objects.filter(pk=data.get("mill"), is_active=True).first() if data.get("mill") else None
        if mill is None:
            raise ValidationError({"mill": "Select the customer / mill."})
        contact = None
        if data.get("contact"):
            contact = MillContact.objects.filter(pk=data["contact"]).first()
            if contact is None:
                raise ValidationError({"contact": "Unknown contact."})
        lead = Lead.objects.filter(pk=data["lead"]).first() if data.get("lead") else None
        activity = None
        if data.get("activity"):
            activity = Activity.objects.filter(pk=data["activity"]).first()
            if activity is None:
                raise ValidationError({"activity": "Unknown activity."})
            if not self.is_admin and activity.assigned_to_id != request.user.pk:
                raise PermissionDenied("This activity is not assigned to you.")
        visit_date = parse_date(str(data.get("visit_date") or ""))
        if visit_date is None:
            raise ValidationError({"visit_date": "Visit date is required (YYYY-MM-DD)."})
        visit_time = None
        if data.get("visit_time"):
            from django.utils.dateparse import parse_time
            visit_time = parse_time(str(data["visit_time"]))
            if visit_time is None:
                raise ValidationError({"visit_time": "Use HH:MM."})
        for key in ("details", "order", "trial"):
            if data.get(key) is not None and not isinstance(data.get(key), dict):
                raise ValidationError({key: "Must be an object."})
        visit_type = data.get("visit_type") or "mill_visit"
        if visit_type not in dict(VISIT_TYPES):
            raise ValidationError({"visit_type": "Unknown visit type."})
        try:
            visit = services.record_visit(
                user=request.user, mill=mill, lead=lead, contact=contact, activity=activity,
                purpose=data.get("purpose") or "", visit_date=visit_date, visit_time=visit_time,
                visit_type=visit_type, people_met=data.get("people_met") or "",
                summary=data.get("summary") or "", outcome=data.get("outcome") or "",
                details=data.get("details") or {}, next_action=data.get("next_action") or "",
                next_followup_date=data.get("next_followup_date") or None,
                order=data.get("order") or {}, trial=data.get("trial") or {},
            )
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            _raise(exc)
        return Response(VisitSerializer(visit).data, status=status.HTTP_201_CREATED)


class TodayPlanView(APIView):
    """Today's Plan: planned activities of a day, follow-ups due that day and
    the day's visits, with completed / planned counts."""

    authentication_classes = SALES_AUTH
    permission_classes = [IsSalesUser]

    def get(self, request):
        user = request.user
        admin = services.is_sales_admin(user)
        day = parse_date(request.query_params.get("date") or "") or timezone.localdate()
        today = timezone.localdate()
        activities = Activity.objects.select_related("mill", "contact", "assigned_to", "created_by").filter(date=day)
        reminders = Reminder.objects.select_related("mill", "lead", "assigned_to").filter(reminder_date=day)
        visits = Visit.objects.select_related("mill", "lead", "contact", "order", "trial", "created_by").filter(
            visit_date=day)
        if not admin or request.query_params.get("mine"):
            activities = activities.filter(assigned_to=user)
            reminders = reminders.filter(assigned_to=user)
            visits = visits.filter(created_by=user)
        elif request.query_params.get("assigned_to"):
            activities = activities.filter(assigned_to_id=request.query_params["assigned_to"])
            reminders = reminders.filter(assigned_to_id=request.query_params["assigned_to"])
            visits = visits.filter(created_by_id=request.query_params["assigned_to"])
        live = activities.exclude(status="cancelled")
        live_reminders = reminders.exclude(status__in=["cancelled", "superseded"])

        def pair(qs):
            return {"completed": qs.filter(status="completed").count(), "planned": qs.count()}

        followups = pair(live.filter(activity_type="followup"))
        followups["completed"] += live_reminders.filter(status="completed").count()
        followups["planned"] += live_reminders.count()
        pending = live.filter(status="pending").count() + live_reminders.filter(status="pending").count()
        overdue_acts = Activity.objects.filter(status="pending", date__lt=today)
        if not admin:
            overdue_acts = overdue_acts.filter(assigned_to=user)
        return Response({
            "date": day,
            "is_today": day == today,
            "visits": pair(live.filter(activity_type="visit")),
            "calls": pair(live.filter(activity_type="call")),
            "followups": followups,
            "pending": pending,
            "overdue": overdue_acts.count(),
            "recorded_visits": visits.count(),
            "activities": ActivitySerializer(live.order_by("time", "created_at"), many=True).data,
            "reminders": ReminderSerializer(live_reminders.order_by("status", "created_at"), many=True).data,
            "visit_records": VisitSerializer(visits, many=True).data,
        })


# ---------------------------------------------------------------------------
# Reminders + notifications
# ---------------------------------------------------------------------------

class ReminderViewSet(SalesViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ReminderSerializer

    def get_queryset(self):
        qs = Reminder.objects.select_related("mill", "lead", "assigned_to", "created_by")
        if not self.is_admin:
            qs = qs.filter(assigned_to=self.request.user)
        params = self.request.query_params
        today = timezone.localdate()
        bucket = params.get("bucket", "pending")
        if bucket == "today":
            qs = qs.filter(status="pending", reminder_date=today)
        elif bucket == "upcoming":
            qs = qs.filter(status="pending", reminder_date__gt=today)
        elif bucket == "overdue":
            qs = qs.filter(status="pending", reminder_date__lt=today)
        elif bucket == "pending":
            qs = qs.filter(status="pending")
        elif bucket == "completed":
            qs = qs.filter(status="completed").order_by("-completed_at")
        elif bucket == "history":
            pass
        if params.get("lead"):
            qs = qs.filter(lead_id=params["lead"])
        if params.get("type"):
            qs = qs.filter(reminder_type=params["type"])
        if params.get("assigned_to") and self.is_admin:
            qs = qs.filter(assigned_to_id=params["assigned_to"])
        return qs

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        reminder = self.get_object()
        try:
            services.complete_reminder(reminder, request.user, notes=request.data.get("notes") or "")
        except DjangoValidationError as exc:
            _raise(exc)
        return Response(ReminderSerializer(reminder).data)

    @action(detail=True, methods=["post"])
    def reschedule(self, request, pk=None):
        reminder = self.get_object()
        new_date = _date_param(request, "reminder_date")
        if new_date is None:
            raise ValidationError({"reminder_date": "Pick a date."})
        try:
            new = services.reschedule_reminder(reminder, request.user, new_date, notes=request.data.get("notes") or "")
        except DjangoValidationError as exc:
            _raise(exc)
        return Response(ReminderSerializer(new).data)


class NotificationViewSet(SalesViewMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = NotificationSerializer

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user)

    def list(self, request, *args, **kwargs):
        services.generate_due_reminder_notifications(request.user)
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        services.generate_due_reminder_notifications(request.user)
        return Response({"unread": self.get_queryset().filter(is_read=False).count()})

    @action(detail=True, methods=["post"], url_path="read")
    def mark_read(self, request, pk=None):
        note = get_object_or_404(self.get_queryset(), pk=pk)
        note.is_read = True
        note.save(update_fields=["is_read"])
        return Response(NotificationSerializer(note).data)

    @action(detail=False, methods=["post"], url_path="read-all")
    def mark_all_read(self, request):
        count = self.get_queryset().filter(is_read=False).update(is_read=True)
        return Response({"updated": count})


# ---------------------------------------------------------------------------
# Dashboard, search, admin monitoring
# ---------------------------------------------------------------------------

PIPELINE_GROUPS = [
    ("new_leads", "New Leads", ["initial_introduction"]),
    ("requirements", "Requirements", ["requirement_discussion"]),
    ("samples", "Samples", ["sample_requested", "sample_delivered"]),
    ("trials", "Trials", ["trial", "trial_followup"]),
    ("opportunities", "Opportunities", ["order_discussion"]),
    ("orders_expected", "Orders / Repeat", ["order_received", "repeat_order_followup", "repeat_order"]),
]


def dashboard_counts(user):
    admin = services.is_sales_admin(user)
    today = timezone.localdate()
    month_start = today.replace(day=1)
    leads = Lead.objects.all() if admin else Lead.objects.filter(assigned_to=user)
    activities = Activity.objects.all() if admin else Activity.objects.filter(assigned_to=user)
    reminders = Reminder.objects.all() if admin else Reminder.objects.filter(assigned_to=user)
    visits = Visit.objects.all() if admin else Visit.objects.filter(created_by=user)
    trials = TrialOrder.objects.all() if admin else TrialOrder.objects.filter(
        Q(lead__assigned_to=user) | Q(created_by=user)).distinct()
    orders = SalesOrder.objects.all() if admin else SalesOrder.objects.filter(
        Q(created_by=user) | Q(lead__assigned_to=user)).distinct()
    enquiries = StockEnquiry.objects.all() if admin else StockEnquiry.objects.filter(created_by=user)
    today_acts = activities.filter(date=today).exclude(status="cancelled")
    data = {
        "today_activities": today_acts.count(),
        "today_visits_planned": today_acts.filter(activity_type="visit").count(),
        "today_visits_completed": today_acts.filter(activity_type="visit", status="completed").count(),
        "today_calls_planned": today_acts.filter(activity_type="call").count(),
        "today_calls_completed": today_acts.filter(activity_type="call", status="completed").count(),
        "visits_recorded_today": visits.filter(visit_date=today).count(),
        "pending_activities": activities.filter(status="pending").count(),
        "overdue_activities": activities.filter(status="pending", date__lt=today).count(),
        "today_reminders": reminders.filter(status="pending", reminder_date=today).count(),
        "overdue_reminders": reminders.filter(status="pending", reminder_date__lt=today).count(),
        "open_leads": leads.filter(status="open").count(),
        "draft_leads": leads.filter(status="draft").count(),
        "trial_orders": trials.filter(status__in=["trial_created", "trial_pending"]).count(),
        "trials_in_progress": trials.filter(status="trial_in_progress").count(),
        "successful_trials": trials.filter(status__in=["trial_successful", "order_followup", "order_placed"]).count(),
        "orders_placed": orders.exclude(status__in=["draft", "cancelled"]).count(),
        "repeat_orders": orders.filter(order_type="repeat").count(),
        "repeat_order_followups": leads.filter(status="open", stage__in=["order_received", "repeat_order_followup",
                                                                         "repeat_order"]).count(),
        "pending_stock_enquiries": enquiries.filter(is_resolved=False).exclude(stock_status="IN_STOCK").count(),
        "orders_under_review": orders.filter(status__in=["placed", "under_review"]).count(),
    }
    data["month"] = {
        "visits": visits.filter(visit_date__gte=month_start).count(),
        "calls": activities.filter(activity_type="call", status="completed", date__gte=month_start).count()
        + visits.filter(visit_date__gte=month_start, visit_type="phone_call").count(),
        "new_leads": leads.filter(created_at__date__gte=month_start).count(),
        "requirements": visits.filter(visit_date__gte=month_start, purpose="requirement_discussion").count(),
        "trials": trials.filter(created_at__date__gte=month_start).count(),
        "orders": orders.filter(created_at__date__gte=month_start).exclude(status="cancelled").count(),
    }
    if admin:
        executives = services.sales_executives()
        data.update({
            "total_mills": Mill.objects.count(),
            "active_mills": Mill.objects.filter(is_active=True).count(),
            "total_leads": Lead.objects.count(),
            "prathap_activities": Activity.objects.filter(assigned_to__in=executives).count(),
            "orders_this_month": SalesOrder.objects.filter(created_at__date__gte=month_start).exclude(
                status="cancelled").count(),
            "trials_this_month": TrialOrder.objects.filter(created_at__date__gte=month_start).count(),
        })
    open_leads = leads.filter(status="open")
    pipeline = {code: open_leads.filter(stage=code).count() for code, _ in JOURNEY_STEPS}
    pipeline["no_further_action"] = leads.filter(status="closed").count()
    groups = [{"key": key, "label": label, "stages": stages, "count": open_leads.filter(stage__in=stages).count()}
              for key, label, stages in PIPELINE_GROUPS]
    return data, pipeline, groups


def _repeat_opportunities(user, admin):
    leads = Lead.objects.filter(status="open", stage__in=["order_received", "repeat_order_followup",
                                                          "repeat_order"]).select_related("mill")
    if not admin:
        leads = leads.filter(assigned_to=user)
    rows = []
    for lead in leads.order_by("reminder_date")[:10]:
        last = lead.orders.exclude(status="cancelled").order_by("-created_at").first()
        rows.append({
            "lead": str(lead.pk), "lead_number": lead.number, "mill": str(lead.mill_id), "mill_name": lead.mill.name,
            "stage": lead.stage, "reminder_date": lead.reminder_date,
            "last_order_number": last.number if last else None,
            "last_order_quantity": last.order_quantity if last else None,
            "last_order_required_m": last.required_m if last else None,
            "last_order_date": last.created_at.date() if last else None,
        })
    return rows


class DashboardView(APIView):
    authentication_classes = SALES_AUTH
    permission_classes = [IsSalesUser]

    def get(self, request):
        user = request.user
        services.generate_due_reminder_notifications(user)
        counts, pipeline, pipeline_groups = dashboard_counts(user)
        admin = services.is_sales_admin(user)
        today = timezone.localdate()
        activities = Activity.objects.select_related("mill", "contact", "assigned_to")
        reminders = Reminder.objects.select_related("mill", "lead", "assigned_to")
        if not admin:
            activities = activities.filter(assigned_to=user)
            reminders = reminders.filter(assigned_to=user)
        recent_orders = SalesOrder.objects.select_related("mill", "traveller_type", "traveller_no", "finish",
                                                          "created_by")
        if not admin:
            recent_orders = recent_orders.filter(created_by=user)
        return Response({
            "user": SessionUserSerializer(user).data,
            "date": today,
            "counts": counts,
            "pipeline": pipeline,
            "pipeline_groups": pipeline_groups,
            "overdue_followups": ReminderSerializer(reminders.filter(status="pending", reminder_date__lt=today)
                                                    .order_by("reminder_date")[:10], many=True).data,
            "upcoming_followups": ReminderSerializer(reminders.filter(status="pending", reminder_date__gt=today)
                                                     .order_by("reminder_date")[:10], many=True).data,
            "repeat_order_opportunities": _repeat_opportunities(user, admin),
            "active_trials": TrialOrderSerializer(
                (TrialOrder.objects.all() if admin else TrialOrder.objects.filter(
                    Q(lead__assigned_to=user) | Q(created_by=user))).filter(
                    status__in=["trial_created", "trial_pending", "trial_in_progress"]).select_related(
                    "mill", "lead", "finish").distinct()[:10], many=True).data,
            "today_plan": ActivitySerializer(activities.filter(date=today).exclude(status="cancelled")[:10],
                                             many=True).data,
            "due_reminders": ReminderSerializer(reminders.filter(status="pending", reminder_date__lte=today)
                                                .order_by("reminder_date")[:10], many=True).data,
            "recent_orders": SalesOrderSerializer(recent_orders[:5], many=True).data,
            "unread_notifications": Notification.objects.filter(recipient=user, is_read=False).count(),
        })


class SearchView(APIView):
    authentication_classes = SALES_AUTH
    permission_classes = [IsSalesUser]

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        if len(q) < 2:
            return Response({"mills": [], "leads": [], "orders": [], "trials": [], "contacts": []})
        admin = services.is_sales_admin(request.user)
        leads = Lead.objects.select_related("mill", "contact", "assigned_to")
        orders = SalesOrder.objects.select_related("mill", "traveller_type", "traveller_no", "finish", "created_by")
        trials = TrialOrder.objects.select_related("mill", "lead", "finish")
        if not admin:
            leads = leads.filter(assigned_to=request.user)
            orders = orders.filter(Q(created_by=request.user) | Q(lead__assigned_to=request.user))
            trials = trials.filter(Q(created_by=request.user) | Q(lead__assigned_to=request.user))
        mills = Mill.objects.filter(is_active=True).filter(
            Q(name__icontains=q) | Q(city__icontains=q) | Q(gstin__icontains=q) | Q(primary_contact__icontains=q)
            | Q(traveller_number__icontains=q) | Q(existing_traveller_used__icontains=q)
            | Q(contacts__name__icontains=q)).distinct()[:10]
        contacts = MillContact.objects.select_related("mill").filter(
            Q(name__icontains=q) | Q(phone__icontains=q), is_active=True)[:10]
        leads = leads.filter(Q(number__icontains=q) | Q(mill__name__icontains=q) | Q(contact__name__icontains=q)
                             | Q(traveller_number__icontains=q) | Q(wire_section__icontains=q)).distinct()[:10]
        orders = orders.filter(Q(number__icontains=q) | Q(mill__name__icontains=q)
                               | Q(traveller_type__name__icontains=q) | Q(traveller_no__code__iexact=q)).distinct()[:10]
        trials = trials.filter(Q(number__icontains=q) | Q(mill__name__icontains=q)
                               | Q(product_type__icontains=q) | Q(batch__icontains=q)).distinct()[:10]
        return Response({
            "mills": MillListSerializer(mills, many=True).data,
            "contacts": [{"id": str(c.id), "name": c.name, "designation": c.designation, "phone": c.phone,
                          "mill": str(c.mill_id), "mill_name": c.mill.name} for c in contacts],
            "leads": LeadListSerializer(leads, many=True).data,
            "orders": SalesOrderSerializer(orders, many=True).data,
            "trials": TrialOrderSerializer(trials, many=True).data,
        })


class MonitoringView(APIView):
    """Admin: what each sales user did, plus the latest audit trail."""

    authentication_classes = SALES_AUTH
    permission_classes = [IsSalesAdmin]

    def get(self, request):
        today = timezone.localdate()
        week_ago = today - timedelta(days=7)
        people = []
        for u in services.sales_executives():
            acts = Activity.objects.filter(assigned_to=u)
            people.append({
                "user": UserMiniSerializer(u).data,
                "activities_today": acts.filter(date=today).count(),
                "activities_completed_7d": acts.filter(status="completed", completed_at__date__gte=week_ago).count(),
                "activities_pending": acts.filter(status="pending").count(),
                "activities_overdue": acts.filter(status="pending", date__lt=today).count(),
                "open_leads": Lead.objects.filter(assigned_to=u, status="open").count(),
                "visits_today": Visit.objects.filter(created_by=u, visit_date=today).count(),
                "visits_7d": Visit.objects.filter(created_by=u, visit_date__gte=week_ago).count(),
                "reminders_overdue": Reminder.objects.filter(assigned_to=u, status="pending",
                                                             reminder_date__lt=today).count(),
                "orders_7d": SalesOrder.objects.filter(created_by=u, created_at__date__gte=week_ago).count(),
                "trials_7d": TrialOrder.objects.filter(created_by=u, created_at__date__gte=week_ago).count(),
                "last_login": u.last_login,
            })
        sales_entities = ["Mill", "MillContact", "Lead", "TrialOrder", "SalesOrder", "Activity", "Reminder", "Visit"]
        logs = AuditLog.objects.filter(entity_type__in=sales_entities).select_related("user")[:50]
        return Response({
            "people": people,
            "audit": [{"action": l.action, "entity_type": l.entity_type, "description": l.description,
                       "user": l.user.username if l.user else None, "created_at": l.created_at} for l in logs],
            "orders_awaiting_review": SalesOrderSerializer(
                SalesOrder.objects.filter(status__in=["placed", "under_review"]).select_related(
                    "mill", "traveller_type", "traveller_no", "finish", "created_by")[:20], many=True).data,
            "trials_awaiting_review": TrialOrderSerializer(
                TrialOrder.objects.filter(status="trial_created").select_related("mill", "lead", "finish")[:20],
                many=True).data,
        })
