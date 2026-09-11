# Rover Traveller

Manufacturing management system tracking the full production workflow:

```
Raw Material → Rolling → Forming → Heat Treatment → Finishing → Finished Goods
```

Built with Django 5, Django REST Framework, PostgreSQL, and a server-rendered
Bootstrap 5 UI. Every screen reads and writes real data through the ORM —
nothing on the transactional screens is mocked.

## Stack

- Python 3.12, Django 5.0, Django REST Framework
- PostgreSQL (single database, one schema per Django app)
- django-environ for environment-based configuration
- WhiteNoise for static files, Gunicorn for production serving
- Bootstrap 5 + Bootstrap Icons (CDN) for the UI

## Project Layout

```
rover-traveller/
├── config/            Django project settings, URLs, WSGI/ASGI
├── apps/
│   ├── accounts/      Users, roles, auth screens, seed_demo_data command
│   ├── dashboard/     KPI dashboard, nav context processor, template tags
│   ├── master_data/   Materials, products, vendors, locations, machines...
│   ├── production/    Production orders, lots, shared stage services
│   ├── rolling/       Rolling transactions
│   ├── forming/       Forming transactions
│   ├── heat_treatment/  Heat treatment transactions
│   ├── finishing/     Finishing transactions
│   ├── finished_goods/  FG receiving, QC approval, hold/reject
│   ├── inventory/     Raw material / WIP / FG stock, transfers, adjustments
│   ├── reports/       Production, process, traceability, rejection reports
│   └── audit/         Audit log + request-scoped middleware
├── static/
│   ├── templates/     Server-rendered HTML (Bootstrap 5)
│   ├── css/, js/, images/
├── fixtures/, media/, scripts/
```

## Local Setup (without Docker)

```bash
python -m venv env
# Windows (cmd.exe)
env\Scripts\activate
# Windows (PowerShell)
.\env\Scripts\Activate.ps1
# Linux/macOS
source env/bin/activate

pip install -r requirements.txt
cp .env.example .env   # edit DB_* values if needed
```

Create the PostgreSQL database (adjust user/host as needed):

```sql
CREATE DATABASE rover_traveller;
```

Then:

Migration files are generated locally rather than committed to git, so run
`makemigrations` once after cloning:

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
python manage.py collectstatic --noinput
python manage.py runserver
```

Visit **http://127.0.0.1:8000/** (or **http://localhost:8000/**).

Convenience scripts that automate the steps above are in `scripts/setup.sh`
(Linux/macOS) and `scripts/setup.ps1` (Windows).

The database starts **completely empty** — no seeded materials, orders, lots,
transactions, or stock. The only thing that exists after setup is the admin
account you create with `createsuperuser`. Everything else (roles, plants,
locations, machines, materials, products, production orders, lots, and every
stage transaction) is created dynamically through the UI or the API from that
point on.

## Docker

```bash
docker compose up --build
```

This starts PostgreSQL with a persistent volume, applies migrations, collects
static files, and serves the app with Gunicorn on **http://localhost:8000/**.
Create your admin account with `docker compose exec web python manage.py
createsuperuser` after the containers are up. The app also runs standalone
without Docker (see above).

## Optional: Demo/Sample Data

A `seed_demo_data` management command is included if you want a realistic
sample dataset to explore the workflow with (master data, one production
order, three lots at different pipeline stages, and the resulting
stock/ledger entries) — it is **not** run automatically:

```bash
python manage.py seed_demo_data
```

It creates its own `admin` / `RoverAdmin@123` superuser plus one demo user per
role (`manager`, `rolling_op`, `forming_op`, `ht_op`, `finishing_op`, `fg_op`,
`inspector`, `inventory_mgr`, `viewer` — all with password `Rover@123`). Run
`python manage.py flush` first if you want to return to a clean, empty
database afterwards.

## Business Rules Enforced

- Input quantity must be greater than zero; output + rejection cannot exceed input.
- A lot only advances to the next stage once its current-stage transaction is completed.
- Completed transactions are immutable — corrections go through stock adjustments.
- Every stock movement writes a `StockTransaction` ledger row; stock can never go negative.
- Finished goods cannot be marked "available" without quality approval.
- Stage completion and finished-goods approval are limited to authorized roles
  (`User.can_operate_stage()` / `User.can_approve()`), enforced in the service
  layer used by both the UI and the API.
- Every stage completion writes an `AuditLog` entry.
- Full traceability from a finished-goods lot back to the raw material lot via
  `Production Lots → Lot Traceability`.

## REST API

All endpoints live under `/api/` and require session authentication (log in
through the browser first, or POST to `/api/auth/login/`).

```
/api/auth/login/            /api/auth/logout/         /api/auth/me/
/api/dashboard/summary/
/api/materials/             /api/products/            /api/vendors/
/api/locations/             /api/machines/            /api/employees/
/api/production-orders/     /api/lots/
/api/rolling/                (+ /{id}/complete/)
/api/forming/                (+ /{id}/complete/)
/api/heat-treatment/         (+ /{id}/complete/)
/api/finishing/               (+ /{id}/complete/)
/api/finished-goods/         (+ /receive/, /{id}/approve/, /{id}/reject/)
/api/inventory/raw-material/
/api/inventory/wip/
/api/inventory/finished-goods/
/api/inventory/transactions/
/api/inventory/transfers/    (+ /{id}/complete/)
/api/inventory/adjustments/
/api/reports/production/
/api/reports/traceability/?lot_number=LOT-2026-00001
```

All list endpoints support filtering, search, ordering, and pagination via
`django-filter` + DRF.

## Tests

```bash
python manage.py test
```

20 tests covering: login, role-based permissions, material/product creation,
production order/lot creation, quantity validation, the full
Rolling → Forming → Heat Treatment → Finishing → Finished Goods pipeline with
stock deduction at every step, duplicate-completion prevention, insufficient-stock
rejection, stock transfers, negative-stock prevention, finished-goods
quality-approval gating, and audit log creation. All 20 currently pass.

## Notes

- `DEBUG=True` and the bundled `SECRET_KEY` in `.env.example` are for local
  development only — replace both before any real deployment.
- The seed command is idempotent for master data (safe to re-run) but skips
  re-creating its three demo lots if they already exist; use
  `python manage.py flush` first if you want a clean re-seed.
