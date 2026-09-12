"""Configuration-driven registry of the five manufacturing processes.

Every process declares, in one place, its data source, its Main Table
columns and its Complete Table columns. The sidebar submenus, the
`/process/<slug>/main|complete/` routes and both table screens are all
generated from this registry, so adding a sixth process means adding one
entry here - no new views, templates, routes or menu markup.

Weight label convention (see ``Column`` usages below):
  * "Received Weight" - the weight handed over BY the previous process,
    auto-fetched, never typed by the user.
  * "Output Weight"   - the weight this process itself recorded.
Rolling is the origin process, so it issues wire from coils ("Weight
Issued") instead of receiving a weight from an earlier process.

Process order lives in the ``PROCESSES`` list at the bottom of this file
and nowhere else: ``ProcessConfig.previous``/``.next`` are resolved from
it, and every "what comes next" decision in the codebase goes through
them rather than a stage-name literal.
"""

from dataclasses import dataclass

from django.apps import apps
from django.db.models import Count, Q
from django.urls import reverse


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
    create_url_name = ""
    create_label = ""
    # Button offered on an incoming row from the previous process.
    initiate_label = "Initiate"
    # ORM path from one of this process's records to the ProductionLot it
    # hands to the next process (see apps/production/handover.py).
    handover_lot_path = "lot"
    # How this process's finished records are ordered when they appear as
    # incoming rows on the next process. Every record exposes `completed_at`
    # through the handover contract, but the terminal process serves it as
    # a property rather than a column, so the ORM path is declared here.
    handover_ordering = "-completed_at"
    # Prefix of the batch number this process stamps on its records, when
    # it records one at all (HT-2604-001, FN-2604-001).
    batch_prefix = ""
    # The status a record carries once it has finished here. Rolling and
    # the OperationBase stages spell it differently, so the vocabulary
    # lives with the process rather than in the completion service.
    completed_status = ""

    # Statuses that are still open work. Rows in these statuses belong on
    # the Main Table (alongside material that has not started yet);
    # everything else has finished here and belongs on the Complete Table
    # - and, once finished, shows up on the next process's Main Table.
    open_statuses = ()

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
        """Open work only: anything finished has moved on."""
        qs = self.base_queryset()
        if self.open_statuses:
            qs = qs.filter(**{f"{self.status_field}__in": list(self.open_statuses)})
        return qs

    def complete_queryset(self, request):
        """Everything that finished here - partially or fully completed."""
        qs = self.base_queryset()
        if self.open_statuses:
            qs = qs.exclude(**{f"{self.status_field}__in": list(self.open_statuses)})
        return qs

    def status_choices(self, submenu="main"):
        """Only offer the statuses a given table can actually contain."""
        choices = self.model._meta.get_field(self.status_field).choices or []
        if not self.open_statuses:
            return choices
        if submenu == "main":
            return [(code, label) for code, label in choices if code in self.open_statuses]
        return [(code, label) for code, label in choices if code not in self.open_statuses]

    # ------------------------------------------------------------------
    # Neighbours - the only place process order is known
    # ------------------------------------------------------------------
    @property
    def index(self):
        return PROCESSES.index(self)

    @property
    def previous(self):
        """The process that hands material to this one, or None if this is
        the origin process."""
        position = self.index
        return PROCESSES[position - 1] if position > 0 else None

    @property
    def next(self):
        """The process this one hands material to, or None if terminal."""
        position = self.index
        return PROCESSES[position + 1] if position + 1 < len(PROCESSES) else None

    # ------------------------------------------------------------------
    # Incoming rows - material the previous process completed and this
    # process has not picked up yet. One implementation, no slug literals,
    # so a sixth process added to PROCESSES gets this for free.
    # ------------------------------------------------------------------
    def claimed_lot_ids(self):
        """Lots this process has already taken up. A cancelled or rejected
        record does not count as taken - otherwise the lot would vanish
        from both tables and get stuck."""
        qs = self.model.objects.exclude(**{f"{self.status_field}__in": ["cancelled", "rejected"]})
        return list(qs.values_list(f"{self.handover_lot_path}_id", flat=True))

    def incoming_queryset(self, request):
        previous = self.previous
        if previous is None:
            return None
        path = previous.handover_lot_path
        return (
            previous.complete_queryset(request)
            .filter(**{f"{path}__isnull": False})
            .exclude(**{f"{path}__in": self.claimed_lot_ids()})
            .order_by(previous.handover_ordering)
            .distinct()
        )

    def incoming_status_cell(self):
        previous = self.previous
        label = f"Incoming from {previous.label}" if previous else "Incoming"
        return {"kind": "status", "code": "incoming", "value": label}

    def incoming_action(self, record):
        lot = record.handover_lot
        if lot is None or not self.create_url_name:
            return []
        return [
            {
                "label": self.initiate_label,
                "url": f"{reverse(self.create_url_name)}?lot={lot.pk}",
                "style": "primary",
            }
        ]

    def row_actions(self, obj):
        return []

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------
    def build_cells(self, obj, columns, *, incoming=False):
        """`incoming=True` renders a predecessor record through the
        handover contract, using each column's `pending` accessor."""
        cells = []
        for column in columns:
            if column.kind == "status":
                cells.append(self.incoming_status_cell() if incoming else _status_cell(obj, column.accessor))
                continue
            path = column.pending if incoming else column.accessor
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

    def build_incoming_rows(self, records, columns):
        return [
            {"cells": self.build_cells(record, columns, incoming=True),
             "actions": self.incoming_action(record), "pending": True}
            for record in records
        ]


# ----------------------------------------------------------------------
# Columns every process downstream of the origin shares. Because every
# record class implements the same handover contract, one accessor works
# for a real row and for an incoming row from the previous process.
# ----------------------------------------------------------------------
IDENTITY_COLUMNS = (
    Column("Wire Serial", "wire_serial", pending="wire_serial", strong=True,
           order_by="lot__source_rolling_batch__wire_serial"),
    Column("Traveller Type", "traveller_type.name", pending="traveller_type.name",
           order_by="lot__source_rolling_batch__traveller_type__name"),
    Column("Traveller No", "traveller_no.code", pending="traveller_no.code"),
)

RECEIVED_WEIGHT_COLUMN = Column(
    "Received Weight (kg)", "received_weight", pending="output_weight", kind="number", order_by="input_quantity"
)

STATUS_COLUMN = Column("Status", "status", kind="status", order_by="status")

# Where the material is physically sitting. `rack_slot_label` is part of the
# handover contract (apps/production/handover.py), so one accessor serves a
# real row and an incoming row from the previous process alike, and only the
# processes that actually place material on a rack ever fill it.
RACK_SLOT_COLUMN = Column("Rack Slot", "rack_slot_label", pending="rack_slot_label")


# ----------------------------------------------------------------------
# P1 - Rolling (origin process: own wire-serial / coil module)
# ----------------------------------------------------------------------
class RollingProcess(ProcessConfig):
    slug = "rolling"
    label = "Rolling"
    icon = "bi-arrow-repeat"
    model_path = "rolling.RollingBatch"
    select_related = ("traveller_type", "traveller_no", "finish")
    annotations = {"coil_count": Count("coils_used", distinct=True)}
    search_fields = ("wire_serial", "traveller_type__name", "traveller_no__code", "finish__finish_name")
    search_placeholder = "Search wire serial, traveller type, finish..."
    create_url_name = "rolling:create"
    create_label = "New Rolling Batch"
    open_statuses = ("In Progress",)
    completed_status = "Completed"
    handover_lot_path = "production_lots"

    main_columns = (
        Column("Wire Serial", "wire_serial", strong=True, order_by="wire_serial"),
        Column("Traveller Type", "traveller_type.name", order_by="traveller_type__name"),
        Column("Traveller No", "traveller_no.code"),
        Column("Surface Finish", "finish.finish_name"),
        Column("Wire Dia (mm)", "wire_diameter_mm", kind="number"),
        Column("Weight Issued (kg)", "wire_weight_issued_kg", kind="number", order_by="wire_weight_issued_kg"),
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
        RACK_SLOT_COLUMN,
        Column("Status", "status", kind="status", order_by="status"),
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

    select_related = ("lot", "lot__source_rolling_batch__traveller_type", "machine")
    ordering = "-created_at"
    # Draft/in-progress is open work; completed, rejected and cancelled
    # records have left this stage and live on the Complete Table.
    open_statuses = ("draft", "in_progress")
    completed_status = "completed"

    # Columns every stage shows, before its process-specific ones.
    identity_columns = IDENTITY_COLUMNS
    # Main Table: only the weight handed over, since nothing here has
    # produced an output weight yet.
    weight_columns = (RECEIVED_WEIGHT_COLUMN, STATUS_COLUMN)

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
    label = "Forming"
    icon = "bi-bounding-box"
    model_path = "forming.FormingTransaction"
    create_url_name = "forming:create"
    create_label = "New Forming Transaction"
    search_fields = ("transaction_number", "lot__source_rolling_batch__wire_serial", "machine__code")
    search_placeholder = "Search wire serial, transaction, machine..."

    main_columns = (
        *StageProcess.identity_columns,
        Column("Surface Finish", "surface_finish.finish_name", pending="surface_finish.finish_name"),
        RACK_SLOT_COLUMN,
        *StageProcess.weight_columns,
    )

    complete_columns = (
        *StageProcess.identity_columns,
        Column("Surface Finish", "surface_finish.finish_name"),
        Column("Machine", "machine.code"),
        Column("Date", "operation_date", kind="date"),
        Column("Received Weight (kg)", "received_weight", kind="number"),
        Column("Output Weight (kg)", "output_quantity", kind="number"),
        Column("Traveller Length (mm)", "traveller_length_mm", kind="number"),
        Column("Traveller Weight (kg)", "traveller_weight_kg", kind="number"),
        Column("Wastage (kg)", "wastage_kg", kind="number"),
        Column("Wastage %", "wastage_percent", kind="number"),
        Column("Status", "status", kind="status", order_by="status"),
    )


class HeatTreatmentProcess(StageProcess):
    slug = "heat_treatment"
    label = "Heat Treatment"
    icon = "bi-fire"
    model_path = "heat_treatment.HeatTreatmentTransaction"
    batch_prefix = "HT"
    create_url_name = "heat_treatment:create"
    create_label = "New Heat Treatment Transaction"
    select_related = StageProcess.select_related + ("surface_finish",)
    search_fields = ("transaction_number", "lot__source_rolling_batch__wire_serial", "batch_number")
    search_placeholder = "Search wire serial, batch no..."

    main_columns = (*StageProcess.identity_columns, *StageProcess.weight_columns)

    complete_columns = (
        *StageProcess.identity_columns,
        Column("Batch No", "batch_number"),
        Column("Surface Finish", "surface_finish.finish_name"),
        Column("Date", "operation_date", kind="date"),
        Column("Received Weight (kg)", "received_weight", kind="number"),
        Column("Output Weight (kg)", "output_quantity", kind="number"),
        Column("Status", "status", kind="status", order_by="status"),
    )


class FinishingProcess(StageProcess):
    slug = "finishing"
    label = "Finishing"
    icon = "bi-brightness-high"
    model_path = "finishing.FinishingTransaction"
    batch_prefix = "FN"
    create_url_name = "finishing:create"
    create_label = "New Finishing Transaction"
    select_related = StageProcess.select_related + ("surface_finish",)
    search_fields = ("transaction_number", "lot__source_rolling_batch__wire_serial", "batch_no", "colour")
    search_placeholder = "Search wire serial, batch no, colour..."

    main_columns = (*StageProcess.identity_columns, *StageProcess.weight_columns)

    complete_columns = (
        *StageProcess.identity_columns,
        Column("Batch No", "batch_no"),
        Column("Surface Finish", "surface_finish.finish_name"),
        Column("Colour", "colour"),
        Column("Machine", "machine.code"),
        Column("Date", "operation_date", kind="date"),
        Column("Received Weight (kg)", "received_weight", kind="number"),
        Column("Output Weight (kg)", "output_quantity", kind="number"),
        Column("Traveller Weight (kg)", "traveller_weight_kg", kind="number"),
        Column("Status", "status", kind="status", order_by="status"),
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
    select_related = ("lot", "lot__source_rolling_batch__traveller_type")
    search_fields = ("fg_lot_number", "lot__source_rolling_batch__wire_serial", "product__product_code")
    search_placeholder = "Search wire serial, FG lot, product..."
    create_url_name = "finished_goods:receive"
    create_label = "Receive Finished Goods"
    initiate_label = "Receive"
    handover_ordering = "-updated_at"
    # Stock on QC hold is still open work; approved/rejected stock is done.
    open_statuses = ("hold",)
    completed_status = "available"

    # Received Weight is a property here (accepted + rejected), so unlike
    # the stages it has no ORM path to sort on.
    received_weight_column = Column(
        "Received Weight (kg)", "received_weight", pending="output_weight", kind="number"
    )

    main_columns = (
        *IDENTITY_COLUMNS,
        received_weight_column,
        STATUS_COLUMN,
    )

    complete_columns = (
        *IDENTITY_COLUMNS,
        RACK_SLOT_COLUMN,
        received_weight_column,
        Column("Output Weight (kg)", "accepted_quantity", kind="number", order_by="accepted_quantity"),
        STATUS_COLUMN,
    )

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


def process_sequence():
    """The process slugs in pipeline order - the single source of truth for
    every "which stage comes next" question in the codebase."""
    return [process.slug for process in PROCESSES]


def process_for_app_label(app_label):
    """The process implemented by a given app, so a model can find its own
    process without writing its slug down."""
    for process in PROCESSES:
        if process.model._meta.app_label == app_label:
            return process
    return None


def process_for_record(record):
    """The process a given record belongs to, resolved by model class."""
    for process in PROCESSES:
        if isinstance(record, process.model):
            return process
    return None
