"""Idempotent: the sales roles and the small sales masters. Safe for every
environment (these are reference values, not business transactions)."""
from django.core.management.base import BaseCommand

from apps.accounts.models import Role
from apps.masters.models import SurfaceFinish
from apps.sales.models import SalesMasterValue

ROLES = [
    ("sales_admin", "Sales Admin", "Monitors the sales pipeline and reviews orders/trials."),
    ("sales_executive", "Sales Executive", "Field sales (Prathap): leads, visits, trials, orders."),
]

VALUES = {
    "ring_profile": ["CR", "AW"],
    "fibre_type": ["Synthetic", "Cotton"],
    "delivery_mode": ["Direct", "Courier"],
    "brand": ["Rover", "Other"],
    "existing_traveller": ["Rover", "Competitor", "Other"],
    "frequency": ["7 Days", "15 Days", "30 Days", "45 Days", "60 Days"],
    "designation": ["Owner", "Managing Director", "General Manager", "Spinning Master", "Production Manager",
                    "Purchase Manager", "Maintenance Manager", "Other"],
    "make": ["LMW", "Rieter", "Toyota", "Other"],
    "ring_make": ["Rieter", "LMW", "Other"],
}


class Command(BaseCommand):
    help = "Create the sales roles and default sales master values (idempotent)."

    def handle(self, *args, **options):
        for code, name, desc in ROLES:
            Role.objects.get_or_create(code=code, defaults={"name": name, "description": desc})
        created = 0
        for category, labels in VALUES.items():
            for index, label in enumerate(labels, start=1):
                _, was_created = SalesMasterValue.objects.get_or_create(
                    category=category, code=label.lower().replace(" ", "_"),
                    defaults={"label": label, "sort_order": index})
                created += was_created
        # The finishes the sales screens use come from the production master.
        if not SurfaceFinish.objects.exists():
            for name in ["Indigo", "Endura", "Plain/Polish", "Nickel +", "NMAX"]:
                SurfaceFinish.objects.get_or_create(finish_name=name)
        self.stdout.write(self.style.SUCCESS(f"Sales roles ready; {created} master values added."))
