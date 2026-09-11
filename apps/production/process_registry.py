"""Configuration-driven registry of the five manufacturing processes.

Every process declares, in one place, its data source, its Main Table
columns and its Complete Table columns. The sidebar submenus, the
`/process/<slug>/main|complete/` routes and both table screens are all
generated from this registry, so adding a sixth process means adding one
entry here - no new views, templates, routes or menu markup.

Weight label convention (see ``Column`` usages below):
  * "Finished Weight" - the weight handed over BY the previous process,
    auto-fetched, never typed by the user.
  * "Output Weight"   - the weight this process itself recorded.
Rolling is the origin process, so it issues wire from coils ("Weight
Issued") instead of receiving a finished weight from an earlier stage.
"""

from dataclasses import dataclass, field

from django.apps import apps
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.urls import reverse

# Status codes rendered as "badge-status-<code>" by rover.css.
PENDING_STATUS = {"code": "pending", "value": "Pending"}


@dataclass(frozen=True)
class Column:
    """One table column. `accessor` is a dotted path resolved against the
    row object; `pending` is the equivalent path when the row is a lot
    still awaiting initiation (blank = leave the cell empty); `order_by`
    is the ORM path that makes the column sortable (blank = not sortable)."""

    label: str
    accessor: str = ""
    pending: str = ""
    kind: str = "text"  # text | number | date | time | datetime | status | bool
    strong: bool = False
    order_by: str = ""

    @property
    def key(self):
        """Stable identifier used in the ?sort= query parameter."""
        return self.order_by


def resolve(obj, path):
    """Walk a dotted accessor path, calling any callables along the way."""
    if not path or obj is None:
        return None
    value = obj
    for part in path.split("."):
        if value is None:
            return None
        value = getattr(value, part, None)
        if callable(value):
            value = value()
    if value == "":
        return None
    return value


def pending_lots_for_stage(stage):
    """Lots whose previous process is done but which have no transaction
    at `stage` yet, annotated with `wip_quantity` - the weight that
    process actually handed over (the WIP balance staged for this stage),
    never the lot's original quantity, which does not shrink as material
    moves down the line."""
    lot_model = apps.get_model("production.ProductionLot")
    wip_model = apps.get_model("inventory.WIPStock")
    handed_over = (
        wip_model.objects.filter(stage=stage, lot=OuterRef("pk"), status="available")
        .order_by("-created_at")
        .values("quantity")[:1]
    )
    return (
        lot_model.objects.filter(current_stage=stage)
        .annotate(wip_quantity=Coalesce(Subquery(handed_over), F("quantity")))
        .select_related("source_rolling_batch")
        .order_by("-created_at")
    )


def _status_cell(obj, accessor):
    raw = resolve(obj, accessor)
    if raw is None:
        return {"kind": "status", "code": "draft", "value": "-"}
    display = getattr(obj, f"get_{accessor}_display", None)
    label = display() if callable(display) else str(raw)
    return {"kind": "status", "code": str(raw).lower().replace(" ", "_"), "value": label}


class ProcessConfig:
    """Base adapter. Subclasses bind a process to its model and columns."""

    slug = ""
    label = ""
    icon = ""
    model_path = ""
    select_related = ()
    annotations = {}
    search_fields = ()
    search_placeholder = "Search..."
    status_field = "status"
    ordering = "-created_at"
    main_columns = ()
    complete_columns = ()
    main_description = ""
    complete_description = ""
    create_url_name = ""
    create_label = ""

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    @property
    def model(self):
        return apps.get_model(self.model_path)

    def base_queryset(self):
        qs = self.model.objects.all()
        if self.select_related:
            qs = qs.select_related(*self.select_related)
        if self.annotations:
            qs = qs.annotate(**self.annotations)
        return qs.order_by(self.ordering)

    def filter_queryset(self, qs, *, status="", search=""):
        if status:
            qs = qs.filter(**{self.status_field: status})
        if search and self.search_fields:
            query = Q()
            for field_name in self.search_fields:
                query |= Q(**{f"{field_name}__icontains": search})
            qs = qs.filter(query)
        return qs

    def sort_queryset(self, qs, columns, *, sort="", direction="asc"):
        """Apply ?sort=/?dir= only when it names a column that declared
        itself sortable, so a hand-typed parameter can never inject an
        arbitrary ORM path."""
        allowed = {column.order_by for column in columns if column.order_by}
        if sort in allowed:
            return qs.order_by(f"-{sort}" if direction == "desc" else sort)
        return qs

    def main_queryset(self, request):
        return self.base_queryset()

    def complete_queryset(self, request):
        return self.base_queryset()

    def status_choices(self):
        return self.model._meta.get_field(self.status_field).choices or []

    # ------------------------------------------------------------------
    # Rows awaiting initiation (shown at the top of the Main Table)
    # ------------------------------------------------------------------
    def pending_rows(self, request):
        return []

    def pending_actions(self, lot):
        return []

    def row_actions(self, obj):
        return []

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------
    def build_cells(self, obj, columns, *, pending=False):
        cells = []
        for column in columns:
            if column.kind == "status":
                cells.append(PENDING_STATUS | {"kind": "status"} if pending else _status_cell(obj, column.accessor))
                continue
            path = column.pending if pending else column.accessor
            cells.append(
                {
                    "kind": column.kind,
                    "value": resolve(obj, path) if path else None,
                    "strong": column.strong,
                }
            )
        return cells

    def build_rows(self, objects, columns):
        return [{"cells": self.build_cells(obj, columns), "actions": self.row_actions(obj)} for obj in objects]

    def build_pending_rows(self, lots, columns):
        return [
            {"cells": self.build_cells(lot, columns, pending=True), "actions": self.pending_actions(lot), "pending": True}
            for lot in lots
        ]


# ----------------------------------------------------------------------
# P1 - Rolling (origin process: own wire-serial / coil module)
# ----------------------------------------------------------------------
class RollingProcess(ProcessConfig):
    slug = "rolling"
    label = "Rolling"
    icon = "bi-arrow-repeat"
    model_path = "rolling.RollingBatch"
    select_related = ("traveller_type", "traveller_no", "finish", "created_by")
    annotations = {"coil_count": Count("coils_used", distinct=True)}
    search_fields = ("wire_serial", "traveller_type__name", "traveller_no__code", "finish__finish_name")
    search_placeholder = "Search wire serial, traveller type, finish..."
    create_url_name = "rolling:create"
    create_label = "New Rolling Batch"
    main_description = "Rolling batches in progress and completed, with the wire serial issued against each."
    complete_description = "Every Rolling record with the full batch specification, coil draw and completion values."

    main_columns = (
        Column("Wire Serial", "wire_serial", strong=True, order_by="wire_serial"),
        Column("Traveller Type", "traveller_type.name", order_by="traveller_type__name"),
        Column("Traveller No", "traveller_no.code"),
        Column("Surface Finish", "finish.finish_name"),
        Column("Weight Issued (kg)", "wire_weight_issued_kg", kind="number", order_by="wire_weight_issued_kg"),
        Column("Output Weight (kg)", "finished_weight_kg", kind="number", order_by="finished_weight_kg"),
        Column("Wastage (kg)", "wastage_kg", kind="number"),
        Column("Status", "status", kind="status", order_by="status"),
    )

    complete_columns = (
        Column("Wire Serial", "wire_serial", strong=True, order_by="wire_serial"),
        Column("Traveller Type", "traveller_type.name", order_by="traveller_type__name"),
        Column("Traveller No", "traveller_no.code"),
        Column("Surface Finish", "finish.finish_name"),
        Column("Wire Dia (mm)", "wire_diameter_mm", kind="number"),
        Column("F-Thickness (mm)", "f_thickness_mm", kind="number"),
        Column("F-Width (mm)", "f_width_mm", kind="number"),
        Column("Required Box", "required_box", kind="number"),
        Column("Weight Issued (kg)", "wire_weight_issued_kg", kind="number", order_by="wire_weight_issued_kg"),
        Column("Coils Used", "coil_count", kind="number"),
        Column("Rolled Thickness (mm)", "rolled_thickness_mm", kind="number"),
        Column("Rolled Width (mm)", "rolled_width_mm", kind="number"),
        Column("Output Weight (kg)", "finished_weight_kg", kind="number", order_by="finished_weight_kg"),
        Column("Wastage (kg)", "wastage_kg", kind="number"),
        Column("Status", "status", kind="status", order_by="status"),
        Column("Created By", "created_by"),
        Column("Created", "created_at", kind="datetime", order_by="created_at"),
        Column("Completed", "completed_at", kind="datetime", order_by="completed_at"),
    )

    def row_actions(self, obj):
        detail = reverse("rolling:detail", kwargs={"pk": obj.pk})
        if obj.status == "Completed":
            return [{"label": "View", "url": detail, "style": "outline-secondary"}]
        return [
            {"label": "Complete", "url": f"{detail}#complete", "style": "success"},
            {"label": "View", "url": detail, "style": "outline-secondary"},
        ]


# ----------------------------------------------------------------------
# P2/P3/P4 - Forming, Heat Treatment, Finishing (generic stage pipeline)
# ----------------------------------------------------------------------
class StageProcess(ProcessConfig):
    """Forming / Heat Treatment / Finishing all run on OperationBase, so
    they share one adapter parameterised by `stage` and column sets."""

    stage = ""
    select_related = ("lot", "lot__source_rolling_batch", "machine", "operator", "shift")
    ordering = "-created_at"

    # Columns every stage shows, before its process-specific ones.
    identity_columns = (
        Column("Wire Serial", "lot.wire_serial", pending="wire_serial", strong=True,
               order_by="lot__source_rolling_batch__wire_serial"),
        Column("Traveller No", "lot.traveller_no", pending="traveller_no"),
        Column("Traveller Date", "lot.traveller_date", pending="traveller_date", kind="date"),
    )
    weight_columns = (
        Column("Finished Weight (kg)", "input_quantity", pending="wip_quantity", kind="number", order_by="input_quantity"),
        Column("Output Weight (kg)", "output_quantity", kind="number", order_by="output_quantity"),
        Column("Status", "status", kind="status", order_by="status"),
    )

    def pending_rows(self, request):
        """Material that finished the previous process but has no
        transaction at this stage yet - the 'Initiate' rows."""
        started = self.model.objects.values_list("lot_id", flat=True)
        return pending_lots_for_stage(self.stage).exclude(pk__in=list(started))

    def pending_actions(self, lot):
        return [
            {
                "label": "Initiate",
                "url": f"{reverse(self.create_url_name)}?lot={lot.pk}",
                "style": "primary",
            }
        ]

    def row_actions(self, obj):
        detail = reverse(f"{self.slug}:detail", kwargs={"pk": obj.pk})
        if obj.status == "completed":
            return [{"label": "View", "url": detail, "style": "outline-secondary"}]
        return [
            {"label": "Complete", "url": reverse(f"{self.slug}:complete", kwargs={"pk": obj.pk}), "style": "success"},
            {"label": "View", "url": detail, "style": "outline-secondary"},
        ]


class FormingProcess(StageProcess):
    slug = "forming"
    stage = "forming"
    label = "Forming"
    icon = "bi-bounding-box"
    model_path = "forming.FormingTransaction"
    create_url_name = "forming:create"
    create_label = "New Forming Transaction"
    search_fields = ("transaction_number", "lot__source_rolling_batch__wire_serial", "machine__code")
    search_placeholder = "Search wire serial, transaction, machine..."
    main_description = "Material received from completed Rolling batches, plus Forming transactions under way."
    complete_description = "Every Forming record with machine, traveller measurements and calculated wastage."

    main_columns = (
        *StageProcess.identity_columns,
        Column("Time Out", "lot.time_out", pending="time_out", kind="time"),
        Column("Date Out", "lot.date_out", pending="date_out", kind="date"),
        Column("Surface Finish", "lot.surface_finish", pending="surface_finish"),
        *StageProcess.weight_columns,
    )

    complete_columns = (
        Column("Transaction #", "transaction_number", strong=True, order_by="transaction_number"),
        *StageProcess.identity_columns,
        Column("Time Out", "lot.time_out", kind="time"),
        Column("Date Out", "lot.date_out", kind="date"),
        Column("Surface Finish", "lot.surface_finish"),
        Column("Machine", "machine.code"),
        Column("Operator", "operator"),
        Column("Shift", "shift.code"),
        Column("Date", "operation_date", kind="date"),
        Column("Finished Weight (kg)", "input_quantity", kind="number"),
        Column("Output Weight (kg)", "output_quantity", kind="number"),
        Column("Traveller Length (mm)", "traveller_length_mm", kind="number"),
        Column("Traveller Weight (kg)", "traveller_weight_kg", kind="number"),
        Column("Wastage (kg)", "wastage_kg", kind="number"),
        Column("Wastage %", "wastage_percent", kind="number"),
        Column("Rejection (kg)", "rejection_quantity", kind="number"),
        Column("Status", "status", kind="status", order_by="status"),
        Column("Created", "created_at", kind="datetime", order_by="created_at"),
    )


class HeatTreatmentProcess(StageProcess):
    slug = "heat_treatment"
    stage = "heat_treatment"
    label = "Heat Treatment"
    icon = "bi-fire"
    model_path = "heat_treatment.HeatTreatmentTransaction"
    create_url_name = "heat_treatment:create"
    create_label = "New Heat Treatment Transaction"
    select_related = StageProcess.select_related + ("surface_finish",)
    search_fields = (
        "transaction_number", "lot__source_rolling_batch__wire_serial", "tt", "t_no", "batch_number", "machine__code",
    )
    search_placeholder = "Search wire serial, TT, T No, batch no..."
    main_description = "Material received from completed Forming transactions, plus Heat Treatment runs under way."
    complete_description = "Every Heat Treatment record with TT, T No, batch, furnace parameters and finished values."

    main_columns = (*StageProcess.identity_columns, *StageProcess.weight_columns)

    complete_columns = (
        Column("Transaction #", "transaction_number", strong=True, order_by="transaction_number"),
        *StageProcess.identity_columns,
        Column("TT", "tt"),
        Column("T No", "t_no"),
        Column("Batch No", "batch_number"),
        Column("Surface Finish", "surface_finish.finish_name"),
        Column("Machine", "machine.code"),
        Column("Operator", "operator"),
        Column("Date", "operation_date", kind="date"),
        Column("HT Type", "get_heat_treatment_type_display"),
        Column("Temperature (C)", "temperature_celsius", kind="number"),
        Column("Holding Time (min)", "holding_time_minutes", kind="number"),
        Column("Finished Weight (kg)", "input_quantity", kind="number"),
        Column("Output Weight (kg)", "output_quantity", kind="number"),
        Column("Rejection (kg)", "rejection_quantity", kind="number"),
        Column("Status", "status", kind="status", order_by="status"),
        Column("Created", "created_at", kind="datetime", order_by="created_at"),
    )


class FinishingProcess(StageProcess):
    slug = "finishing"
    stage = "finishing"
    label = "Finishing"
    icon = "bi-brightness-high"
    model_path = "finishing.FinishingTransaction"
    create_url_name = "finishing:create"
    create_label = "New Finishing Transaction"
    select_related = StageProcess.select_related + ("surface_finish",)
    search_fields = (
        "transaction_number", "lot__source_rolling_batch__wire_serial", "tt", "t_no", "batch_no", "colour",
    )
    search_placeholder = "Search wire serial, TT, T No, batch no, colour..."
    main_description = "Material received from completed Heat Treatment runs, plus Finishing transactions under way."
    complete_description = "Every Finishing record with TT, T No, batch, colour and finished traveller values."

    main_columns = (*StageProcess.identity_columns, *StageProcess.weight_columns)

    complete_columns = (
        Column("Transaction #", "transaction_number", strong=True, order_by="transaction_number"),
        *StageProcess.identity_columns,
        Column("TT", "tt"),
        Column("T No", "t_no"),
        Column("Batch No", "batch_no"),
        Column("Surface Finish", "surface_finish.finish_name"),
        Column("Colour", "colour"),
        Column("Machine", "machine.code"),
        Column("Operator", "operator"),
        Column("Date", "operation_date", kind="date"),
        Column("Finished Weight (kg)", "input_quantity", kind="number"),
        Column("Output Weight (kg)", "output_quantity", kind="number"),
        Column("Traveller Weight (kg)", "traveller_weight_kg", kind="number"),
        Column("Rejection (kg)", "rejection_quantity", kind="number"),
        Column("Status", "status", kind="status", order_by="status"),
        Column("Created", "created_at", kind="datetime", order_by="created_at"),
    )


# ----------------------------------------------------------------------
# P5 - Finished Goods (stock receipt + QC, not an OperationBase stage)
# ----------------------------------------------------------------------
class FinishedGoodsProcess(ProcessConfig):
    slug = "finished_goods"
    stage = "finished_goods"
    label = "Finished Goods"
    icon = "bi-box-seam"
    model_path = "inventory.FinishedGoodsStock"
    select_related = ("product", "lot", "lot__source_rolling_batch", "location", "rack", "shelf", "quality_approved_by")
    search_fields = ("fg_lot_number", "lot__source_rolling_batch__wire_serial", "product__product_code")
    search_placeholder = "Search wire serial, FG lot, product..."
    create_url_name = "finished_goods:receive"
    create_label = "Receive Finished Goods"
    main_description = "Material received from completed Finishing transactions, plus finished goods already booked in."
    complete_description = "Every Finished Goods record with product, storage location and quality decision."

    main_columns = (
        Column("Wire Serial", "lot.wire_serial", pending="wire_serial", strong=True,
               order_by="lot__source_rolling_batch__wire_serial"),
        Column("Traveller No", "lot.traveller_no", pending="traveller_no"),
        Column("Traveller Date", "lot.traveller_date", pending="traveller_date", kind="date"),
        Column("Finished Weight (kg)", "received_quantity", pending="wip_quantity", kind="number"),
        Column("Output Weight (kg)", "accepted_quantity", kind="number", order_by="accepted_quantity"),
        Column("Status", "status", kind="status", order_by="status"),
    )

    complete_columns = (
        Column("FG Batch #", "fg_lot_number", strong=True, order_by="fg_lot_number"),
        Column("Wire Serial", "lot.wire_serial"),
        Column("Traveller No", "lot.traveller_no"),
        Column("Traveller Date", "lot.traveller_date", kind="date"),
        Column("Product", "product.product_code"),
        Column("Location", "location.code"),
        Column("Rack", "rack.code"),
        Column("Shelf", "shelf.code"),
        Column("Finished Weight (kg)", "received_quantity", kind="number"),
        Column("Output Weight (kg)", "accepted_quantity", kind="number", order_by="accepted_quantity"),
        Column("Rejected (kg)", "rejected_quantity", kind="number"),
        Column("QC Approved", "quality_approved", kind="bool"),
        Column("Approved By", "quality_approved_by"),
        Column("Status", "status", kind="status", order_by="status"),
        Column("Created", "created_at", kind="datetime", order_by="created_at"),
    )

    def pending_rows(self, request):
        received = self.model.objects.values_list("lot_id", flat=True)
        return pending_lots_for_stage("finished_goods").exclude(pk__in=list(received))

    def pending_actions(self, lot):
        return [
            {"label": "Receive", "url": f"{reverse('finished_goods:receive')}?lot={lot.pk}", "style": "primary"}
        ]

    def row_actions(self, obj):
        return [
            {"label": "View", "url": reverse("finished_goods:detail", kwargs={"pk": obj.pk}), "style": "outline-secondary"}
        ]


# ----------------------------------------------------------------------
# The registry itself - menu order is registry order.
# ----------------------------------------------------------------------
PROCESSES = [
    RollingProcess(),
    FormingProcess(),
    HeatTreatmentProcess(),
    FinishingProcess(),
    FinishedGoodsProcess(),
]

PROCESS_BY_SLUG = {process.slug: process for process in PROCESSES}


def get_process(slug):
    return PROCESS_BY_SLUG.get(slug)
