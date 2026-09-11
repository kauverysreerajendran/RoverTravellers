# Prompt: Reset process data, generate April→today history through every screen, and add S.No to every table

Paste everything below this line into Claude Code opened at the root of `D:\Workspace\Rover`. This assumes `docs/ROVER_HANDOVER_CHAIN_PROMPT.md` has been applied (registry-driven `previous`/`next`, incoming rows, "Received Weight"). If it has not, apply that first — the generator below depends on it.

---

Read `docs/ROVER_PROCESS_MAP.md`, `apps/production/process_registry.py`, every `services.py` under `apps/`, `apps/masters/management/commands/seed_masters.py`, `apps/accounts/management/commands/seed_demo_data.py` and `static/templates/process/_data_table.html` before changing anything.

## Task 1 — `reset_process_data`: wipe everything that is not master data

Add `apps/production/management/commands/reset_process_data.py`.

* **Protected (never touched, counts asserted identical before and after):** `TravellerType`, `TravellerNo`, `SurfaceFinish`, `DiameterMaster` rows, `RackMaster`, `DiameterTravellerMapping`, `Machine`, `User`, `Role`, `UserRole`. Any other master table that still exists in `apps/master_data` is also protected.
* **Deleted:** every process record — discover them **from the registry** (`process.model` for every entry in `PROCESSES`) plus their child tables (`RollingBatchCoil`, `OperationStatusHistory`, `OperationQualityCheck` if it still exists), `ProductionLot`, `ProductionOrder` if it still exists, `WIPStock`, `StockTransaction`, `FinishedGoodsStock`, `RawMaterialStock`/`StockTransfer`/`StockAdjustment` if they still exist, `AuditLog`. Delete in dependency order inside one `transaction.atomic()`; use `Model.objects.all().delete()` (not raw SQL) so PROTECT FKs surface as errors instead of leaving orphans.
* **Reset, not deleted:** `CoilMaster` rows are deleted (they are stock, not master) and every `DiameterMaster.recalculate_stock()` is called afterwards so `total_stock=0`, `active_coils=0`. `WireSerialMaster` is reset to the seed baseline: everything with `sort_order <= --current-serial` (default `SB110`, same rule as `seed_masters`) stays `Used`, everything after becomes `Available` with `used_at=NULL`.
* Requires `--yes`; without it, print what would be deleted (table → row count) and exit 1. Print the same table after deletion with the protected counts unchanged.

## Task 2 — `seed_process_history`: realistic data from 1 April 2026 to today, through the real services

Add `apps/production/management/commands/seed_process_history.py`. Options: `--from 2026-04-01`, `--to` (default: today, local time `Asia/Kolkata`), `--per-day 2` (batches started per working day, Mon–Sat), `--seed 42` (deterministic), `--reset` (calls `reset_process_data --yes` first), `--extend` (see below).

### 2a. Mappings for every traveller type
Every active `TravellerType` must be usable. For each type **without** a `DiameterTravellerMapping`, create a *provisional* one: diameter = the official 65-row list indexed by `seq_no % 65` (only diameters that exist in `DiameterMaster`), `f_thickness_mm = round(diameter × 0.44, 2)`, `f_width_mm = round(diameter × 1.90, 2)`. Print a clearly marked WARNING block listing every provisional mapping created and telling the operator to replace them with `import_traveller_mappings <csv>` (create that command now if it does not exist: columns `seq_no,diameter_mm,f_thickness_mm,f_width_mm`, upsert by `seq_no`). Never overwrite an existing mapping. `--no-provisional-mappings` aborts instead of creating them.

### 2b. Coils and racks
Racks: if fewer than 6 `RackMaster` rows exist, create `R1`–`R6` (capacity 10). For every diameter referenced by a mapping, receive 3–6 coils via `masters.services.receive_coil` with weights 40.00–95.00 kg, rack round-robin, supplier from a small fixed list, `received_date` spread between `--from` minus 14 days and `--to`. Ensure total coil weight per diameter comfortably covers the batches that will draw on it (compute demand first, then top up).

### 2c. Batches — every traveller type, every date, every stage
* Build the calendar of working days in `[--from, --to]`; on each day start `--per-day` Rolling batches. Choose the traveller type by cycling through **all active types in `seq_no` order** so that after 71 starts every type has been used; then continue cycling. Assert at the end that every active type appears in at least one `RollingBatch`. Rotate `TravellerNo` and `SurfaceFinish` through their masters. `required_box` 1–6. Wire weight issued = sum of 1–3 coil draws (each 10.00–45.00 kg) from In-Stock coils of the mapped diameter.
* Run each batch through the pipeline **only via the service functions the views call** — `rolling.services.initiate_rolling_batch` / `complete_rolling_batch`, the stage initiate path used by `StageCreateView` (factor a `production.services.initiate_stage(process, lot, user, **fields)` out of the view if one does not exist, and make the view call it), `production.services.complete_stage` / `handover`, `finished_goods.services.receive_finished_goods`. No direct ORM creation of transactions. Each stage's output = input × random(0.960, 0.995) rounded to 2 dp; Forming adds traveller length 400–900 mm and traveller weight ≈ output; Finishing adds colour from `["Natural","Blue","Black","Gold"]` and traveller weight; HT/Finishing batch numbers `HT-YYMM-NNN` / `FN-YYMM-NNN`; machines round-robin from `Machine` rows per stage.
* **How far each batch gets is decided by its age**, so every screen has data: age ≥ 12 days → fully received in Finished Goods; 9–11 days → completed Finishing (incoming at FG); 6–8 → completed HT (incoming at Finishing); 4–5 → completed Forming (incoming at HT); 2–3 → completed Rolling (incoming at Forming); 0–1 days → Rolling in progress. Additionally, one in every five batches in each band is left **in progress at that stage** (initiated, not completed) so every Main Table shows both incoming and in-progress rows. Use a per-process day offset (Rolling +0d, Forming +2d, HT +4d, Finishing +6d, FG +8d from the start date) for the operation dates.
* **Backdate timestamps** so the screens show April→today, not "today" for everything: after each service call, set `created_at`, `completed_at`, `operation_date`, `used_at` (wire serial), `received_date` (coil), and the matching `AuditLog`/`OperationStatusHistory`/`StockTransaction.created_at` rows with `Model.objects.filter(pk=...).update(...)` (auto_now fields ignore `save()`). Time of day 08:00–18:00 IST.
* Wire serials are consumed in order from the next Available; if fewer remain than batches planned, stop with a clear error before writing anything (pre-check).
* Wrap the whole run in one `transaction.atomic()`; refuse to run if process tables are non-empty unless `--reset` or `--extend` is given.
* `--extend`: instead of refusing, generate only for dates after the latest existing `RollingBatch.created_at` up to `--to`, so re-running the command daily keeps the demo current. Existing rows are never modified.

### 2d. Chain guarantee (this is the acceptance rule)
At the end of the run, for every consecutive pair `(N, N+1)` in `PROCESSES`, assert: every row in `N.complete_queryset()` has its `handover_lot` present **either** as an incoming row on `N+1` (`N+1.incoming_queryset()`) **or** as a record in `N+1.model` (in progress or completed). Print a summary table: per process — incoming, in progress, completed; total traveller types used / total active; first and last batch date. Fail loudly if any assertion breaks.

Update `README.md` with the three commands and the order: `seed_masters` → `seed_process_history --reset` (first time) → `seed_process_history --extend` (daily).

## Task 3 — S.No on every front-end table

* `static/templates/process/_data_table.html`: add a first column `S.No` (header `<th class="col-sno">S.No</th>`). Numbering is continuous: incoming rows are numbered 1…k, then data rows continue from `k+1` and across pages, i.e. row number = `k + page_obj.start_index + forloop.counter0` (compute `k` in the view context as `incoming_count`, do not do arithmetic with nested template filters). The colspan of the empty-state row increases by one.
* Add a template tag `{% load rover_extras %}` → `{% sno page_obj forloop.counter0 offset %}` in `apps/dashboard/templatetags/rover_extras.py` that returns the continuous number, and use it in **every** other table that lists rows: `masters/rack_locator.html`, `masters/diameter_list.html`, `masters/diameter_detail.html` (coils), `rolling/rolling_detail.html` (coils — already numbered, switch to the tag), `dashboard/overview.html` (every table), every template under `reports/`, and any list template that still exists under `production/` or `inventory/`. S.No is always the first column, right-aligned, class `col-sno`, width ~56px in `rover.css`.
* S.No is presentation only: never sortable, never a model field, never part of search or filters.
* Tests: (1) for every process Main and Complete Table, the first `<th>` text is `S.No`; (2) with 30 completed Forming rows and `per_page=25`, page 2's first data row is numbered 26; (3) with 3 incoming rows and 2 in-progress rows on a Main Table, the numbers rendered are 1–5 in order; (4) a generic test that renders every template containing `<table` under `static/templates/` (through their real views with seeded data) and asserts the first header cell is `S.No`.

## Working rules

Order: Task 1 → Task 2 → Task 3, with `python manage.py check`, `makemigrations --check` and `python manage.py test` green after each, one commit per task. Do not create data with raw ORM inserts where a service exists — the point of the generator is that it proves the real flow works. Do not hardcode process slugs anywhere in the generator; iterate `PROCESSES` and use `process.previous/next`. Do not modify master lists (`TRAVELLER_TYPES`, `DIAMETERS_MM`) in `seed_masters`. Provisional mappings are the only fabricated master data, and they must be printed as a warning every run they are created.

Finish by running, on a fresh database: `migrate` → `seed_masters` → `seed_process_history --reset --from 2026-04-01` and paste the summary table it prints, plus the full test run output.
