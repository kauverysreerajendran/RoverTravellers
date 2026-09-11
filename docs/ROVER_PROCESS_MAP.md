# Rover — How the process actually works today (as-built, read from code on 11 Sep 2026)

This is a factual map of what the code in `D:\Workspace\Rover` does right now. It is the baseline the cleanup prompt refers to.

## 1. Master data (end to end)

There are **two separate master-data layers**, and this is the root of most of the mess.

### 1a. Rover-specific masters — `apps/masters` (the real ones)

| Master | Model | Source of truth | Notes |
|---|---|---|---|
| Traveller Type | `TravellerType` (seq_no, name) | PDF list 1–68 + client corrections (69 H2 HO, 70 RSY FLAT, 71 RSY Rd) | `seq_no` is the business key; "RE2 UDR" repeats at 17 and 63 |
| Traveller No | `TravellerNo` (code) | seed: "1", "0", "1/0".."25/0", "1".."35" | `label` field is dead ("Pending label" hack) |
| Surface Finish | `SurfaceFinish` | seed: Indigo, Endura, Plain/Polish, Nickel +, NMAX | |
| Raw Material (Diameter) | `DiameterMaster` (RM-093 = 0.93 mm) | PDF list, 65 official rows | seed ALSO adds a provisional 0.10–0.98 fill (≈+54 rows) |
| Coil | `CoilMaster` (child of Diameter) | Received via Inventory → Diameter detail screen | numbering restarts at 1 when no In-Stock coils remain; `DiameterMaster.total_stock/active_coils` recalculated from coils |
| Rack (coil racks) | `RackMaster` (rack_code, capacity) | Rack locator screen | |
| Diameter ↔ Traveller Type mapping | `DiameterTravellerMapping` (traveller_type → raw_material, F-thickness, F-width) | **only ONE row seeded: U1UM UDR → RM-093 / 0.41 / 1.78** | 70 of 71 types have no mapping → Rolling refuses them. No UI exists to maintain this table (admin only). |
| Wire Serial | `WireSerialMaster` SA01–SA1000, SB01–SB1000, SC01–SC1000 | seed; everything up to SB110 pre-marked Used | Rolling claims the next Available row in order (row-locked) |
| Machine | `Machine` (code 1A…9B, stage) | seeded only by `seed_demo_data`, not `seed_masters` | has a mandatory FK to `master_data.Plant` |

### 1b. Generic ERP masters — `apps/master_data` (leftover scaffolding)

`UnitOfMeasure, Plant, Department, Location, Rack, Shelf, Tray, Vendor, Shift, Employee, ProcessMaster, ReasonCode, MaterialMaster, ProductMaster, ProductSpecification`, each with its own list/create/edit screens under `/master-data/...` (not in the sidebar, but reachable).

These are **not part of the Rover business**, yet the pipeline still silently depends on some of them:

* `inventory.services._default_location()` needs at least one `Location` row or it raises *"No location master data configured."* → **completing a Rolling batch on a fresh DB (seed_masters only) fails.**
* `Machine.plant` needs a `Plant` row → cannot create a machine on a fresh DB.
* Finished-Goods receiving needs a `ProductMaster` and an FG-type `Location`.
* `rolling.services._stage_rolling_output_for_forming` auto-creates placeholder rows `MaterialMaster "RM-ROLLING-WIRE"`, `ProductMaster "WIP-ROLLED-WIRE"`, a `ProductionOrder` and a `ProductionLot` on every Rolling completion.

Two different "Rack" masters exist (`masters.RackMaster` for coils, `master_data.Rack→Shelf→Tray` for FG stores) and two different "Inventory" concepts (`DiameterMaster/CoilMaster` vs `RawMaterialStock/WIPStock/FinishedGoodsStock` + transfers/adjustments/ledger).

## 2. How a process is initiated and how it moves Main → Complete

All ten screens are generated from one registry: `apps/production/process_registry.py`. Routes are `/process/<slug>/main/` and `/process/<slug>/complete/`; two generic views in `process_views.py`; one template `process/_data_table.html`.

**Rule of the registry:** each process declares `open_statuses`. Rows in an open status are on the **Main Table**; anything else is on the **Complete Table**. The Main Table additionally shows *pending rows* (material handed over by the previous process that has no transaction here yet) with an **Initiate** button.

### P1 Rolling (origin) — `apps/rolling`
1. **Initiate** (`/rolling/create/`, "New Rolling Batch"): user picks Traveller Type → JS calls `/api/traveller-types/<id>/mapping/` → Wire Dia / F-Thickness / F-Width auto-fill → JS calls `/api/coils/?raw_material_id=` → user ticks coils and enters weight per coil; sum must equal "Wire weight to issue". Traveller No, Surface Finish, Required Box entered. `services.initiate_rolling_batch()` claims the next Wire Serial, snapshots the mapping values, consumes coil weight, creates `RollingBatch(status="In Progress")`.
2. Main Table shows it (status "Rolling Inprogress") with **Complete** / **View**.
3. **Complete** (detail page form → `/rolling/<pk>/complete/`): Rolled Thickness, Rolled Width, Output (finished) Weight. `complete_rolling_batch()` sets wastage = issued − finished, status "Completed", `completed_at`, **then bridges to P2**: creates a `ProductionLot(current_stage="forming", source_rolling_batch=batch)` and `WIPStock(stage="forming", quantity=finished_weight)`.
4. Row moves to Rolling Complete Table and appears as a *pending row* on Forming Main Table.

### P2 Forming / P3 Heat Treatment / P4 Finishing — `StageProcess` on `OperationBase`
1. **Pending row → Initiate** (`/<stage>/create/?lot=`): form fields — Forming: machine, date; HT: batch no, date, surface finish; Finishing: batch no, date, surface finish, machine. `input_quantity` ("Finished Weight") is forced server-side from the previous stage's WIP balance. Creates transaction `status="in_progress"` (or `draft` via "Save as Draft"). Duplicate open transaction per lot is blocked.
2. Main Table row shows **Complete** / **View**.
3. **Complete** (`/<stage>/<pk>/complete/`): Forming: output weight, traveller length, traveller weight; HT: output weight; Finishing: output weight, traveller weight, colour. `production.services.complete_stage()` consumes this stage's WIP, adds WIP for the next stage, sets status `completed`, advances `lot.current_stage`, writes `OperationStatusHistory` + `AuditLog`. Wastage kg/% is computed **only for Forming** (field exists only there).
4. Row → Complete Table; lot appears as pending row on the next stage's Main Table.

### P5 Finished Goods — `FinishedGoodsProcess` on `inventory.FinishedGoodsStock`
1. Pending row → **Receive** (`/finished-goods/receive/?lot=`): form needs Product, Location, Rack/Shelf/Tray, accepted + rejected quantity. Consumes `finished_goods` WIP, creates `FinishedGoodsStock(status="hold")`.
2. Main Table shows it as *hold* (open status). Detail page offers **Approve & Mark Available / Reject / Put On Hold** (the QC gate) — approval requires `can_approve()` roles.
3. approved/rejected → Complete Table.

## 3. Things that are in the codebase but not part of the Rover process (deviations)

* **QC layer**: `OperationQualityCheck` model, "Quality Checks" table on every stage detail page, Quality Report, FG hold/approve/reject cycle, `quality_approved` fields, `quality_inspector` role in `APPROVAL_ROLES`.
* **Generic production-order layer**: `ProductionOrder`, `ProductionLot` screens (`/production/orders`, `/production/lots`, process tracker), `ProductMaster`, `ProductSpecification`, planned quantities, due dates. Rolling auto-creates a fake order per batch just to satisfy FKs.
* **Generic inventory layer**: `RawMaterialStock`, `StockTransfer`, `StockAdjustment`, stock ledger, low-stock alerts, reorder levels, transfers/adjustments screens; `Location/Plant/Department/Vendor/Shift/Employee/ReasonCode/UnitOfMeasure` masters.
* **Unused transaction fields**: `OperationBase.operator, shift, start_time, end_time, rejection_quantity, rejection_reason`; HT `heat_treatment_type, temperature_celsius, holding_time_minutes, tt, t_no`; Finishing `finishing_operation, surface_finish_spec, tt, t_no`; Forming `forming_operation`. Statuses `draft / rejected / cancelled` and the "Save as Draft" button.
* **Inconsistent status vocabulary**: Rolling stores `"In Progress"/"Completed"`; stages store `in_progress/completed`; FG stores `hold/available/rejected`.
* **Two entry points per stage**: "New Forming Transaction" button (free lot dropdown) *and* Initiate on the pending row.
* **Wastage only on Forming**, although every stage has Finished vs Output weight.
* **seed_masters mixes master data with demo data** (creates rack R1 and 4 dummy coils with a fake supplier; hardcodes current wire serial SB110; adds provisional diameters not in the official 65).
* **Only one traveller-type mapping** and no screen to maintain mappings.
* **Config/hygiene**: ngrok host hardcoded in `settings.py`; `requirements.txt` lists both `psycopg2-binary` and `psycopg[binary]`; `staticfiles/` full of hashed duplicates; README describes the old generic pipeline, says migrations aren't committed (they are), says "20 tests"; `RejectionReportView` crashes on `txn.machine.name` when machine is null (HT).
