"""DEVELOPMENT / UAT ONLY. Creates the sales executive login (Prathap) and a
few demo mills, all tagged source="demo" so they can be found and removed:

    python manage.py seed_sales_demo --password <pw>
    python manage.py seed_sales_demo --purge      # delete demo mills again

Refuses to run when DEBUG is off unless --force is given."""
import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Role, User, UserRole
from apps.sales.models import Mill, MillContact

DEMO_MILLS = [
    {
        "name": "Shree Ganesh Textiles Pvt. Ltd. (DEMO)", "city": "Coimbatore",
        "address": "123, Industrial Area, Coimbatore - 641 021, Tamil Nadu", "gstin": "33AABCS1234D1Z5",
        "contacts": [("Ramesh Kumar", "Production Manager", "+91 98765 43210", True),
                     ("Suresh Babu", "Spinning Master", "+91 98765 43211", False)],
    },
    {
        "name": "ABC Spinning Mills (DEMO)", "city": "Tiruppur",
        "address": "45, Avinashi Road, Tiruppur - 641 603, Tamil Nadu", "gstin": "33AABCA5678E1Z2",
        "contacts": [("Rajesh Kumar", "Production Manager", "+91 90000 11111", True)],
    },
    {
        "name": "XYZ Textiles (DEMO)", "city": "Salem",
        "address": "7, Omalur Main Road, Salem - 636 009, Tamil Nadu", "gstin": "33AABCX9012F1Z9",
        "contacts": [("Mohan Raj", "Purchase Manager", "+91 90000 22222", True)],
    },
]


class Command(BaseCommand):
    help = "Development seed: Prathap (sales executive) login and demo mills (source=demo)."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="prathap")
        parser.add_argument("--password", default="")
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--purge", action="store_true", help="Deactivate demo mills and stop.")

    @transaction.atomic
    def handle(self, *args, **opts):
        if not settings.DEBUG and not opts["force"]:
            raise CommandError("Refusing to seed demo data with DEBUG off. Use --force for UAT.")
        if opts["purge"]:
            count = Mill.objects.filter(source="demo").update(is_active=False)
            self.stdout.write(self.style.WARNING(f"Deactivated {count} demo mills."))
            return
        role, _ = Role.objects.get_or_create(code="sales_executive", defaults={"name": "Sales Executive"})
        user = User.objects.filter(username=opts["username"]).first()
        if user is None:
            password = opts["password"] or secrets.token_urlsafe(9)
            user = User.objects.create_user(username=opts["username"], password=password, first_name="Prathap",
                                            email=f"{opts['username']}@rover.local")
            self.stdout.write(self.style.SUCCESS(f"Created user {user.username} / password: {password}"))
        elif opts["password"]:
            user.set_password(opts["password"])
            user.save()
            self.stdout.write(f"Password reset for {user.username}.")
        UserRole.objects.get_or_create(user=user, role=role)

        for spec in DEMO_MILLS:
            data = {k: v for k, v in spec.items() if k != "contacts"}
            primary = spec["contacts"][0]
            mill, created = Mill.objects.get_or_create(
                name=data["name"],
                defaults={**data, "source": "demo", "primary_contact": primary[0], "designation": primary[1],
                          "contact_number": primary[2]})
            if created:
                for name, designation, phone, is_primary in spec["contacts"]:
                    MillContact.objects.create(mill=mill, name=name, designation=designation, phone=phone,
                                               is_primary=is_primary)
        self.stdout.write(self.style.SUCCESS(f"Demo mills ready ({len(DEMO_MILLS)}). Sales user: {user.username}"))
