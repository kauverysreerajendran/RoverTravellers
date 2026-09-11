import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import ROLE_CHOICES, Role, User, UserRole
from apps.finished_goods import services as fg_services
from apps.finishing.models import FinishingTransaction
from apps.forming.models import FormingTransaction
from apps.heat_treatment.models import HeatTreatmentTransaction
from apps.inventory import services as inv_services
from apps.master_data.models import (
    Department,
    Employee,
    Location,
    Machine,
    MaterialMaster,
    Plant,
    ProcessMaster,
    ProductMaster,
    ProductSpecification,
    Rack,
    ReasonCode,
    Shelf,
    Shift,
    Tray,
    UnitOfMeasure,
    Vendor,
)
from apps.production import services as prod_services
from apps.production.models import ProductionLot, ProductionOrder
from apps.rolling.models import RollingTransaction


def dt(days_ago=0, hour=8, minute=0):
    base = timezone.now() - datetime.timedelta(days=days_ago)
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


class Command(BaseCommand):
    help = "Seed Rover Traveller with realistic demo data for local development."

    def handle(self, *args, **options):
        self.stdout.write("Seeding Rover Traveller demo data...")

        roles = self._seed_roles()
        admin_user = self._seed_users(roles)
        plant = self._seed_plant()
        departments = self._seed_departments(plant)
        locations = self._seed_locations(plant)
        self._seed_racks(locations)
        machines = self._seed_machines(plant)
        vendors = self._seed_vendors()
        shifts = self._seed_shifts()
        employees = self._seed_employees(departments)
        self._seed_processes()
        reason_codes = self._seed_reason_codes()
        uom = self._seed_uom()
        material = self._seed_material(uom, vendors)
        product = self._seed_product(uom, material)

        order = self._seed_production_order(product)

        self._seed_full_pipeline_lot(order, material, product, locations, machines, shifts, employees, reason_codes, admin_user)
        self._seed_mid_pipeline_lot(order, material, locations, machines, shifts, employees, reason_codes, admin_user)
        self._seed_draft_lot(order, material, locations, machines, shifts, employees, admin_user)

        self.stdout.write(self.style.SUCCESS("Demo data seeded successfully."))
        self.stdout.write(self.style.SUCCESS("Login with username 'admin' / password 'RoverAdmin@123'"))

    # ------------------------------------------------------------------
    def _seed_roles(self):
        roles = {}
        for code, name in ROLE_CHOICES:
            role, _ = Role.objects.get_or_create(code=code, defaults={"name": name})
            roles[code] = role
        return roles

    def _seed_users(self, roles):
        admin, created = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@rovertraveller.local",
                "first_name": "Rover",
                "last_name": "Administrator",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created:
            admin.set_password("RoverAdmin@123")
            admin.save()
        UserRole.objects.get_or_create(user=admin, role=roles["super_admin"])

        demo_accounts = [
            ("production_manager", "manager", "Priya", "Menon"),
            ("rolling_operator", "rolling_op", "Arun", "Kumar"),
            ("forming_operator", "forming_op", "Vikram", "Rao"),
            ("heat_treatment_operator", "ht_op", "Suresh", "Nair"),
            ("finishing_operator", "finishing_op", "Deepak", "Iyer"),
            ("finished_goods_operator", "fg_op", "Anita", "Verma"),
            ("quality_inspector", "inspector", "Kavya", "Reddy"),
            ("inventory_manager", "inventory_mgr", "Rahul", "Shah"),
            ("viewer", "viewer", "Neha", "Gupta"),
        ]
        for role_code, username, first, last in demo_accounts:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@rovertraveller.local",
                    "first_name": first,
                    "last_name": last,
                    "is_staff": False,
                },
            )
            if created:
                user.set_password("Rover@123")
                user.save()
            UserRole.objects.get_or_create(user=user, role=roles[role_code])
        return admin

    def _seed_plant(self):
        plant, _ = Plant.objects.get_or_create(
            code="PLANT1", defaults={"name": "Rover Steel Works - Plant 1", "address": "Industrial Area, Chennai, India"}
        )
        return plant

    def _seed_departments(self, plant):
        departments = {}
        for code, name in [("PROD", "Production"), ("QA", "Quality Assurance"), ("STORE", "Stores & Inventory")]:
            dept, _ = Department.objects.get_or_create(plant=plant, code=code, defaults={"name": name})
            departments[code] = dept
        return departments

    def _seed_locations(self, plant):
        locations = {}
        specs = [
            ("RM-STORE", "Raw Material Store", "store"),
            ("WIP-ROLLING", "Rolling WIP Area", "wip"),
            ("WIP-FORMING", "Forming WIP Area", "wip"),
            ("WIP-HT", "Heat Treatment WIP Area", "wip"),
            ("WIP-FINISHING", "Finishing WIP Area", "wip"),
            ("FG-STORE", "Finished Goods Store", "fg"),
            ("QUARANTINE", "Quality Quarantine Zone", "quarantine"),
        ]
        for code, name, ltype in specs:
            loc, _ = Location.objects.get_or_create(plant=plant, code=code, defaults={"name": name, "location_type": ltype})
            locations[code] = loc
        return locations

    def _seed_racks(self, locations):
        rack, _ = Rack.objects.get_or_create(location=locations["FG-STORE"], code="R1")
        shelf, _ = Shelf.objects.get_or_create(rack=rack, code="S1")
        Tray.objects.get_or_create(shelf=shelf, code="T1")
        self.fg_rack = rack
        self.fg_shelf = shelf

    def _seed_machines(self, plant):
        machines = {}
        specs = [
            ("ROL-M1", "Rolling Mill 1", "rolling"),
            ("FRM-M1", "Forming Press 1", "forming"),
            ("HT-M1", "Heat Treatment Furnace 1", "heat_treatment"),
            ("FIN-M1", "Finishing & Polishing Line 1", "finishing"),
        ]
        for code, name, stage in specs:
            m, _ = Machine.objects.get_or_create(code=code, defaults={"name": name, "stage": stage, "plant": plant})
            machines[stage] = m
        return machines

    def _seed_vendors(self):
        vendors = []
        for code, name in [("VEND-01", "Bharat Steel Suppliers"), ("VEND-02", "Southern Metal Traders")]:
            v, _ = Vendor.objects.get_or_create(code=code, defaults={"name": name, "email": f"{code.lower()}@example.com"})
            vendors.append(v)
        return vendors

    def _seed_shifts(self):
        shifts = {}
        specs = [
            ("A", "Morning Shift", datetime.time(6, 0), datetime.time(14, 0)),
            ("B", "Afternoon Shift", datetime.time(14, 0), datetime.time(22, 0)),
            ("C", "Night Shift", datetime.time(22, 0), datetime.time(6, 0)),
        ]
        for code, name, start, end in specs:
            s, _ = Shift.objects.get_or_create(code=code, defaults={"name": name, "start_time": start, "end_time": end})
            shifts[code] = s
        return shifts

    def _seed_employees(self, departments):
        employees = {}
        specs = [
            ("EMP-ROL", "Arun", "Kumar", "rolling_op", "Rolling Operator"),
            ("EMP-FRM", "Vikram", "Rao", "forming_op", "Forming Operator"),
            ("EMP-HT", "Suresh", "Nair", "ht_op", "Heat Treatment Operator"),
            ("EMP-FIN", "Deepak", "Iyer", "finishing_op", "Finishing Operator"),
            ("EMP-FG", "Anita", "Verma", "fg_op", "Finished Goods Operator"),
            ("EMP-QA", "Kavya", "Reddy", "inspector", "Quality Inspector"),
        ]
        for code, first, last, username, designation in specs:
            user = User.objects.filter(username=username).first()
            emp, _ = Employee.objects.get_or_create(
                employee_code=code,
                defaults={
                    "first_name": first, "last_name": last, "department": departments["PROD"],
                    "designation": designation, "user": user, "email": f"{username}@rovertraveller.local",
                },
            )
            employees[code] = emp
        return employees

    def _seed_processes(self):
        specs = [
            ("ROLLING", "Rolling", "rolling", 1),
            ("FORMING", "Forming", "forming", 2),
            ("HEAT_TREAT", "Heat Treatment", "heat_treatment", 3),
            ("FINISHING", "Finishing", "finishing", 4),
            ("FG_PACK", "Finished Goods Packing", "finished_goods", 5),
        ]
        for code, name, stage, seq in specs:
            ProcessMaster.objects.get_or_create(code=code, defaults={"name": name, "stage": stage, "sequence": seq})

    def _seed_reason_codes(self):
        reason_codes = {}
        specs = [
            ("SURF-DEF", "Surface Defect", "rejection"),
            ("DIM-OUT", "Dimension Out of Specification", "rejection"),
            ("PHY-COUNT", "Physical Count Correction", "adjustment"),
            ("LAB-PEND", "Pending Lab Test Result", "hold"),
            ("WRONG-ENTRY", "Wrong Data Entry", "cancellation"),
        ]
        for code, desc, cat in specs:
            rc, _ = ReasonCode.objects.get_or_create(code=code, defaults={"description": desc, "category": cat})
            reason_codes[code] = rc
        return reason_codes

    def _seed_uom(self):
        uom, _ = UnitOfMeasure.objects.get_or_create(code="KG", defaults={"name": "Kilogram"})
        UnitOfMeasure.objects.get_or_create(code="MT", defaults={"name": "Metric Ton"})
        UnitOfMeasure.objects.get_or_create(code="PCS", defaults={"name": "Pieces"})
        UnitOfMeasure.objects.get_or_create(code="MM", defaults={"name": "Millimeter"})
        return uom

    def _seed_material(self, uom, vendors):
        material, _ = MaterialMaster.objects.get_or_create(
            material_code="RM-STEEL-100",
            defaults={
                "name": "Steel Billet 100mm", "material_type": "raw_material", "unit_of_measure": uom,
                "grade": "EN8", "standard_diameter_mm": Decimal("100.000"), "default_vendor": vendors[0],
                "reorder_level": Decimal("500.000"),
            },
        )
        return material

    def _seed_product(self, uom, material):
        product, _ = ProductMaster.objects.get_or_create(
            product_code="FG-ROD-12MM",
            defaults={"name": "Steel Rod 12mm", "unit_of_measure": uom, "raw_material": material},
        )
        ProductSpecification.objects.get_or_create(
            product=product, parameter_name="Diameter",
            defaults={"min_value": Decimal("11.8"), "max_value": Decimal("12.2"), "target_value": Decimal("12.0"), "unit": "mm"},
        )
        ProductSpecification.objects.get_or_create(
            product=product, parameter_name="Surface Hardness",
            defaults={"min_value": Decimal("180"), "max_value": Decimal("220"), "target_value": Decimal("200"), "unit": "HB"},
        )
        return product

    def _seed_production_order(self, product):
        order = ProductionOrder.objects.filter(product=product, status="in_progress").first()
        if not order:
            order = ProductionOrder.objects.create(
                product=product, planned_quantity=Decimal("5000.000"), uom="KG", status="in_progress",
                due_date=timezone.now().date() + datetime.timedelta(days=14),
                remarks="Initial demo production order for Steel Rod 12mm.",
            )
        return order

    # ------------------------------------------------------------------
    def _seed_full_pipeline_lot(self, order, material, product, locations, machines, shifts, employees, reason_codes, admin_user):
        if ProductionLot.objects.filter(production_order=order, remarks__icontains="DEMO-LOT-COMPLETE").exists():
            return
        lot = ProductionLot.objects.create(production_order=order, quantity=Decimal("1000.000"), remarks="DEMO-LOT-COMPLETE")

        inv_services.receive_raw_material(
            material, Decimal("2000.000"), location=locations["RM-STORE"], user=admin_user, remarks="Initial GRN from vendor"
        )

        rolling = RollingTransaction.objects.create(
            lot=lot, raw_material=material, machine=machines["rolling"], operator=employees["EMP-ROL"], shift=shifts["A"],
            start_time=dt(5, 6), end_time=dt(5, 12), input_quantity=Decimal("1000.000"), output_quantity=Decimal("950.000"),
            rejection_quantity=Decimal("30.000"), rejection_reason=reason_codes["SURF-DEF"], status="in_progress",
            created_by=admin_user, updated_by=admin_user,
        )
        prod_services.complete_rolling(rolling, admin_user, material=material, location=locations["RM-STORE"])

        forming = FormingTransaction.objects.create(
            lot=lot, forming_operation="Cold Forming", machine=machines["forming"], operator=employees["EMP-FRM"],
            shift=shifts["A"], start_time=dt(4, 6), end_time=dt(4, 12), input_quantity=Decimal("950.000"),
            output_quantity=Decimal("900.000"), rejection_quantity=Decimal("30.000"), rejection_reason=reason_codes["DIM-OUT"],
            status="in_progress", created_by=admin_user, updated_by=admin_user,
        )
        prod_services.complete_stage(forming, admin_user, current_stage="forming")

        heat_treat = HeatTreatmentTransaction.objects.create(
            lot=lot, batch_number="HTB-0001", heat_treatment_type="normalizing", temperature_celsius=Decimal("870.00"),
            holding_time_minutes=Decimal("45.00"), machine=machines["heat_treatment"], operator=employees["EMP-HT"],
            shift=shifts["B"], start_time=dt(3, 14), end_time=dt(3, 16), input_quantity=Decimal("900.000"),
            output_quantity=Decimal("870.000"), rejection_quantity=Decimal("20.000"), status="in_progress",
            created_by=admin_user, updated_by=admin_user,
        )
        prod_services.complete_stage(heat_treat, admin_user, current_stage="heat_treatment")

        finishing = FinishingTransaction.objects.create(
            lot=lot, finishing_operation="Surface Polishing", surface_finish_spec="Ra 1.6", machine=machines["finishing"],
            operator=employees["EMP-FIN"], shift=shifts["A"], start_time=dt(2, 6), end_time=dt(2, 12),
            input_quantity=Decimal("870.000"), output_quantity=Decimal("850.000"), rejection_quantity=Decimal("15.000"),
            status="in_progress", created_by=admin_user, updated_by=admin_user,
        )
        prod_services.complete_stage(finishing, admin_user, current_stage="finishing")

        fg_stock = fg_services.receive_finished_goods(
            lot=lot, product=product, accepted_quantity=Decimal("800.000"), rejected_quantity=Decimal("50.000"),
            location=locations["FG-STORE"], rack=self.fg_rack, shelf=self.fg_shelf, tray=None, user=admin_user,
            remarks="Received from finishing line",
        )
        fg_services.approve_finished_goods(fg_stock, admin_user, mark_available=True)

    def _seed_mid_pipeline_lot(self, order, material, locations, machines, shifts, employees, reason_codes, admin_user):
        if ProductionLot.objects.filter(production_order=order, remarks__icontains="DEMO-LOT-MIDWAY").exists():
            return
        lot = ProductionLot.objects.create(production_order=order, quantity=Decimal("800.000"), remarks="DEMO-LOT-MIDWAY")

        inv_services.receive_raw_material(
            material, Decimal("900.000"), location=locations["RM-STORE"], user=admin_user, remarks="GRN for lot 2"
        )
        rolling = RollingTransaction.objects.create(
            lot=lot, raw_material=material, machine=machines["rolling"], operator=employees["EMP-ROL"], shift=shifts["B"],
            start_time=dt(2, 14), end_time=dt(2, 20), input_quantity=Decimal("800.000"), output_quantity=Decimal("760.000"),
            rejection_quantity=Decimal("25.000"), rejection_reason=reason_codes["SURF-DEF"], status="in_progress",
            created_by=admin_user, updated_by=admin_user,
        )
        prod_services.complete_rolling(rolling, admin_user, material=material, location=locations["RM-STORE"])

        FormingTransaction.objects.create(
            lot=lot, forming_operation="Cold Forming", machine=machines["forming"], operator=employees["EMP-FRM"],
            shift=shifts["B"], start_time=dt(1, 14), input_quantity=Decimal("400.000"), output_quantity=Decimal("0.000"),
            rejection_quantity=Decimal("0.000"), status="in_progress", created_by=admin_user, updated_by=admin_user,
        )

    def _seed_draft_lot(self, order, material, locations, machines, shifts, employees, admin_user):
        if ProductionLot.objects.filter(production_order=order, remarks__icontains="DEMO-LOT-DRAFT").exists():
            return
        lot = ProductionLot.objects.create(production_order=order, quantity=Decimal("500.000"), remarks="DEMO-LOT-DRAFT")
        inv_services.receive_raw_material(
            material, Decimal("500.000"), location=locations["RM-STORE"], user=admin_user, remarks="GRN for lot 3"
        )
        RollingTransaction.objects.create(
            lot=lot, raw_material=material, machine=machines["rolling"], operator=employees["EMP-ROL"], shift=shifts["C"],
            start_time=dt(0, 22), input_quantity=Decimal("500.000"), output_quantity=Decimal("0.000"),
            rejection_quantity=Decimal("0.000"), status="draft", created_by=admin_user, updated_by=admin_user,
        )
