"""Turn due sales reminders into in-app notifications. Schedule it (Windows
Task Scheduler / cron) at the time set by SALES_REMINDER_NOTIFY_TIME; the API
also runs the same check lazily whenever a user opens the app."""
from django.core.management.base import BaseCommand

from apps.sales.services import generate_due_reminder_notifications


class Command(BaseCommand):
    help = "Create notifications for sales reminders that are due."

    def handle(self, *args, **options):
        count = generate_due_reminder_notifications()
        self.stdout.write(self.style.SUCCESS(f"{count} reminder notification(s) created."))
