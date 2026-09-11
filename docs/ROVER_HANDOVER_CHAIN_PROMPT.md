# Prompt: Make every process's Complete Table row flow into the next process's Main Table — dynamically, from the registry

Paste everything below this line into Claude Code opened at the root of `D:\Workspace\Rover`.

---

Read `docs/ROVER_PROCESS_MAP.md`, then `apps/production/process_registry.py`, `apps/production/process_views.py`, `apps/production/services.py`, `apps/production/stage_views.py`, `apps/rolling/services.py`, `apps/finished_goods/views.py`, `apps/inventory/services.py`, `static/templates/process/_data_table.html` and `apps/production/test_process_screens.py` before changing anything.

## What must be true when you are done

1. **Chain rule.** For every consecutive pair of processes in `PROCESSES` (registry order), every record on process N's **Complete Table** also appears on process N+1's **Main Table** as an *incoming* row until process N+1 has been initiated for it. The last process has no successor; the first has no predecessor. This must hold for any registry — adding a sixth `ProcessConfig` to the list must give it incoming rows from its predecessor and feed its successor with zero extra code.
2. **Label rule.** The weight a process receives from its predecessor is called **"Received Weight (kg)"** everywhere (tables, forms, detail/complete screens, checklists, help text, docstrings, comments). The string "Finished Weight" must not exist anywhere in `apps/` or `static/templates/` afterwards. A process's own result stays "Output Weight (kg)". Rolling stays "Weight Issued (kg)".
3. **Value rule.** On the incoming row, Received Weight == the predecessor record's Output Weight, and when the operator initiates, `input_quantity` is set server-side from that same value. The WIP ledger continues to be written and consumed, but it is a guard, not a display source — the number on screen and the number saved must come from the predecessor record, and a test must assert the WIP balance equals it.
4. **No hardcoding rule.** No stage name literal (`"forming"`, `"heat_treatment"`, …) may be used to decide *what comes next* or *what came before*. The only place process order exists is the `PROCESSES` list. Specifically remove or derive: `NEXT_WIP_STAGE`, `STEPPER_STAGES`, the manual `pending_rows`/`pending_actions` overrides in `StageProcess` and `FinishedGoodsProcess`, `pending_lots_for_stage()`, the `"forming"` literal and `current_stage="forming"` in `rolling.services._stage_rolling_output_for_forming`, the `current_stage=<literal>` filters in the stage forms, and the `stage` string attribute where it merely duplicates `slug`. `LOT_STAGE_CHOICES` must be built from the registry (keep `raw_material` as the only non-process value if migrations need it).

## How to build it (the design; keep it this simple)

### A. A handover contract on every process model
Add a small abstract mixin (e.g. `apps/production/handover.py::HandoverRecord`) that every process record class implements with the **same property names**:

```
wire_serial        -> str
traveller_type     -> TravellerType
traveller_no       -> TravellerNo
surface_finish     -> SurfaceFinish | None
output_weight      -> Decimal | None   # what this record hands to the next process
handover_lot       -> ProductionLot    # the carrier the next process initiates against
completed_at       -> datetime | None
```
`RollingBatch`: `output_weight = finished_weight_kg`, `handover_lot` = its `production_lots` row (create it at initiation time, not completion, so the lot exists for the whole life of the batch; `current_stage` = the Rolling process slug until completion). `OperationBase` subclasses: `output_weight = output_quantity`, `handover_lot = lot`, identity via `lot.source_rolling_batch`. `FinishedGoodsStock`: `output_weight = accepted_quantity`, terminal. Do not duplicate data; these are properties over existing fields. Remove the ad-hoc `wire_serial/traveller_type/traveller_no/surface_finish` properties on `ProductionLot` only if nothing else needs them; otherwise leave them and have the mixin delegate.

### B. Registry knows its neighbours
On `ProcessConfig` add read-only `index`, `previous` and `next` resolved from `PROCESSES` (compute lazily from the list, never stored per class). Add a module-level `process_sequence()` returning the slugs in order, and derive `LOT_STAGE_CHOICES`, the stepper and any "next stage" logic from it.

### C. One generic incoming-rows implementation in the base class
In `ProcessConfig`:
* `incoming_queryset(request)`: `None` if `self.previous is None`; otherwise `self.previous.complete_queryset(request)` excluding records whose `handover_lot` already has a record in `self.model` that is **open or completed** (a cancelled/rejected record, while those statuses still exist, must not hide the incoming row — that is how lots get stuck today). Order by `completed_at` desc.
* `incoming_action(record)`: one button labelled by a per-process attribute `initiate_label` (default "Initiate"; Finished Goods sets "Receive") whose URL is `reverse(self.create_url_name) + f"?lot={record.handover_lot.pk}"`.
* `build_incoming_rows(records, columns)` renders `Column.pending` accessors against the **predecessor record** through the contract (`wire_serial`, `traveller_type.name`, `traveller_no.code`, `surface_finish.finish_name`, `output_weight`). Because the contract is uniform, the Received Weight column in every process is literally `Column("Received Weight (kg)", "input_quantity", pending="output_weight", kind="number", …)` and the identity columns are shared constants — no per-process pending paths.
* Delete the subclass overrides of `pending_rows`/`pending_actions` and `pending_lots_for_stage`. `row_actions` may stay per-process (it depends on the process's own URLs).

### D. Views and template
* `ProcessTableView.load_rows`: incoming rows are part of the Main Table always — they must **not** disappear when a search or status filter is active. Apply the search to incoming rows using the predecessor's `search_fields`; add a virtual status choice `("incoming", "Incoming")` to the Main Table status filter that shows only incoming rows, and make any real status value hide incoming rows. Show the incoming count in the footer ("+ N incoming from <previous label>").
* `_data_table.html`: the incoming `<tr>` keeps the `row-pending` class; the status cell reads "Incoming from <previous label>" (registry-provided, not template-literal).
* Rolling Main Table (no predecessor) renders no incoming section and keeps its "New Rolling Batch" button.

### E. Initiate screens read the predecessor record, not a free lot list
`StageCreateView` and `FinishedGoodsReceiveView`: require `?lot=`, resolve the predecessor record via the registry (`process.previous.model` filtered on `handover_lot`), refuse (message + redirect to Main Table) if the lot is not currently incoming to this process, show the contract fields read-only ("Received Weight (kg)" pre-filled from `output_weight`), and force `input_quantity`/`accepted_quantity` default from it server-side. Remove the `ProductionLot.objects.filter(current_stage="<literal>")` querysets from the four initiate forms; the lot field becomes a hidden input validated against the incoming set.

### F. Completion advances the chain generically
Replace `complete_rolling`/`complete_stage`'s next-stage logic with one `production.services.handover(record, process, user)` that: validates `output_weight` (0 < output ≤ received), stamps `completed_at`/status, sets `record.handover_lot.current_stage = process.next.slug` (or a terminal value from the registry for the last process), writes WIP for `process.next.slug` when a successor exists, records `OperationStatusHistory` + `AuditLog`. `complete_rolling_batch` and `complete_stage` call it; `_stage_rolling_output_for_forming` disappears. The dashboard stepper (`stage_progress`) iterates `PROCESSES`.

### G. Rename
Replace every "Finished Weight" (labels, form `labels={}`, checklists in the four `views.py`, `stage_complete.html`, `stage_detail.html`, `finished_goods_form.html`, `rolling_detail.html` wording, docstrings, the registry header comment, `FinishedGoodsStock.received_quantity` docstring) with "Received Weight". Element ids like `weight-received-value` may stay.

## Tests (update + add; all must pass)

* Rewrite `test_weight_labels_follow_the_agreed_convention`: exactly one label starting with "Received Weight" on every non-Rolling table, zero on Rolling, and no label containing "Finished Weight" anywhere.
* Add `ProcessChainTests` parametrised over `zip(PROCESSES, PROCESSES[1:])` with **no slug literals**: for each pair, create and complete a record at N through its service function; assert it is on N's Complete Table, appears on N+1's Main Table with the correct wire serial, "Received Weight" == N's `output_weight`, an Initiate/Receive link carrying `?lot=`, and that the WIP balance for N+1 equals the same value; initiate at N+1 via the view (`?lot=`); assert it left the incoming list and now shows as an in-progress row with `input_quantity` == that value; assert the incoming row is still visible with a search on its wire serial and with `?status=incoming`, and hidden with `?status=in_progress`.
* Extend `test_a_process_added_to_the_registry_gets_both_screens` so the temporary sixth process (a) receives incoming rows from the last real process and (b) is reported as `next` of it — proving nothing is hardcoded.
* Add a grep-style test that no file under `apps/` (excluding migrations) contains `NEXT_WIP_STAGE`, `STEPPER_STAGES`, `pending_lots_for_stage`, or `current_stage="` with a process slug literal.
* Keep every other test in `test_process_screens.py` green (adjust only text expectations that the rename changes).

## Working rules

Work in this order and run `python manage.py check`, `makemigrations --check` (then generate real migrations) and `python manage.py test` after each step: A → B → C+D → E → F → G → tests. One commit per step. Do not add process-specific views/templates; the registry-driven `process/_data_table.html` stays the only table implementation. Do not touch `rover.css` except the incoming/pending row style if needed. Keep all legacy `*:list` redirects. Do not reintroduce any Location/Product/Plant dependency; if `inventory.services._default_location` blocks a completion on a database seeded with `seed_masters` only, fix that as part of step F (WIP must work without master_data Locations).

Finish with: the list of removed symbols, the migrations created, and the output of the full test run.
