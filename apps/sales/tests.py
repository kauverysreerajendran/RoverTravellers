from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.accounts.models import Role, User, UserRole
from apps.inventory.models import FinishedGoodsStock
from apps.master_data.models import MaterialMaster, ProductMaster, UnitOfMeasure
from apps.masters.models import SurfaceFinish, TravellerNo, TravellerType
from apps.production.models import ProductionLot, ProductionOrder
from apps.rolling.models import RollingBatch

from . import rules, services
from .models import (
    Activity, Lead, LeadEvent, Mill, MillContact, Notification, Reminder, SalesMasterValue, SalesOrder,
    StockEnquiry, TrialOrder, Visit,
)


# ---------------------------------------------------------------------------
# Pure rules
# ---------------------------------------------------------------------------

class ReminderRuleTests(SimpleTestCase):
    today = date(2026, 9, 29)

    def test_default_is_today_plus_15(self):
        for action in ["followup", "requirement_discussion", "sample_requested", "sample_delivered", "trial",
                       "trial_followup", "order_discussion", "order_received", "repeat_order", "initial_introduction"]:
            self.assertEqual(rules.default_reminder_date(action, self.today), date(2026, 10, 14), action)

    def test_no_further_action_has_no_reminder(self):
        self.assertIsNone(rules.default_reminder_date("no_further_action", self.today))
        self.assertEqual(rules.resolve_reminder_date("no_further_action", self.today, date(2026, 10, 1)),
                         (None, None, False))

    def test_repeat_order_is_monthly(self):
        self.assertEqual(rules.default_reminder_date("repeat_order_followup", self.today), date(2026, 10, 29))
        self.assertEqual(rules.add_months(date(2026, 1, 31), 1), date(2026, 2, 28))

    def test_override(self):
        chosen = date(2026, 10, 5)
        self.assertEqual(rules.resolve_reminder_date("followup", self.today, chosen),
                         (chosen, date(2026, 10, 14), True))
        self.assertEqual(rules.resolve_reminder_date("followup", self.today, None),
                         (date(2026, 10, 14), date(2026, 10, 14), False))

    def test_override_in_past_rejected(self):
        with self.assertRaises(ValueError):
            rules.resolve_reminder_date("followup", self.today, date(2026, 9, 1))

    @override_settings(SALES_DEFAULT_REMINDER_DAYS=10)
    def test_default_days_configurable(self):
        self.assertEqual(rules.default_reminder_date("followup", self.today), date(2026, 10, 9))


class TransitionRuleTests(SimpleTestCase):
    def test_journey_steps(self):
        self.assertEqual(len(rules.JOURNEY), 10)
        # New journey: any step can be the first (e.g. an existing customer's repeat order).
        self.assertEqual(rules.allowed_steps(None), rules.JOURNEY)
        self.assertTrue(rules.can_record_step("initial_introduction", "requirement_discussion"))
        self.assertTrue(rules.can_record_step("initial_introduction", "trial"))  # steps can be skipped
        self.assertTrue(rules.can_record_step("trial", "trial"))  # same step again
        self.assertTrue(rules.can_record_step("trial_followup", "trial"))  # repeat trial
        self.assertTrue(rules.can_record_step("repeat_order", "repeat_order_followup"))  # monthly loop
        self.assertFalse(rules.can_record_step("trial", "initial_introduction"))
        self.assertFalse(rules.can_record_step("order_received", "sample_requested"))

    def test_next_actions(self):
        actions = rules.next_actions("initial_introduction")
        self.assertEqual(actions[0], "followup")
        self.assertEqual(actions[-1], "no_further_action")
        self.assertIn("requirement_discussion", actions)
        self.assertNotIn("initial_introduction", actions)
        self.assertIn("trial", rules.next_actions("trial_followup"))
        self.assertIn("repeat_order_followup", rules.next_actions("repeat_order"))
        self.assertEqual(rules.reminder_type_for("trial", "followup"), "trial_followup")
        self.assertEqual(rules.reminder_type_for("order_received", "repeat_order_followup"), "repeat_order")
        self.assertEqual(rules.reminder_type_for("sample_requested", "sample_delivered"), "sample_followup")

    def test_trial_transitions(self):
        self.assertTrue(rules.can_transition_trial("trial_created", "trial_pending"))
        self.assertTrue(rules.can_transition_trial("trial_in_progress", "trial_successful"))
        self.assertTrue(rules.can_transition_trial("trial_failed", "repeat_trial"))
        self.assertFalse(rules.can_transition_trial("trial_successful", "trial_failed"))

    def test_order_transitions(self):
        self.assertTrue(rules.can_transition_order("placed", "confirmed"))
        self.assertTrue(rules.can_transition_order("processing", "dispatched"))
        self.assertFalse(rules.can_transition_order("completed", "placed"))
        self.assertFalse(rules.can_transition_order("cancelled", "confirmed"))

    def test_stock_status(self):
        self.assertEqual(rules.stock_status(Decimal("10"), Decimal("5")), "IN_STOCK")
        self.assertEqual(rules.stock_status(Decimal("3"), Decimal("5")), "PARTIALLY_AVAILABLE")
        self.assertEqual(rules.stock_status(Decimal("0"), Decimal("5")), "OUT_OF_STOCK")
        self.assertEqual(rules.stock_status(Decimal("3"), None), "PARTIALLY_AVAILABLE")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class SalesTestBase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("salesadmin", "a@x.com", "Adm1n@Pass!")
        self.prathap = User.objects.create_user("prathap_t", password="Prath@p123", first_name="Prathap")
        role, _ = Role.objects.get_or_create(code="sales_executive", defaults={"name": "Sales Executive"})
        UserRole.objects.create(user=self.prathap, role=role)
        self.outsider = User.objects.create_user("operator", password="Op3rator!")
        self.mill = Mill.objects.create(name="Test Spinning Mills", address="1 Main Rd", gstin="33AABCS1234D1Z5",
                                        primary_contact="Ramesh", contact_number="999")
        self.contact = MillContact.objects.create(mill=self.mill, name="Ramesh Kumar",
                                                  designation="Production Manager", is_primary=True)
        self.tt = TravellerType.objects.create(seq_no=901, name="U1 UL UDR")
        self.tn = TravellerNo.objects.create(code="14/0")
        self.finish = SurfaceFinish.objects.create(finish_name="Nickel + T")
        for label in ["Direct", "Courier"]:
            SalesMasterValue.objects.get_or_create(category="delivery_mode", code=label.lower(),
                                                   defaults={"label": label})
        self.today = timezone.localdate()

    def client_for(self, user):
        client = APIClient()
        token, _ = Token.objects.get_or_create(user=user)
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return client

    def stage1_lead(self, user=None):
        lead = Lead.objects.create(
            mill=self.mill, contact=self.contact, assigned_to=user or self.prathap, visit_date=self.today,
            total_spindles=25000, frame_details="LR6", make="LMW", ring_make="Rieter", ring_profile="CR", speed="18000",
            count="40s", fibre_type="Cotton", existing_traveller_used="Competitor", brand="Other",
            wire_section="Flat", surface_finish="Nickel", traveller_number="14/0", frequency_of_change="15 Days",
            sample_quantity="1000",
        )
        return lead


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class AuthApiTests(SalesTestBase):
    def test_login_returns_token_and_role(self):
        client = APIClient()
        res = client.post("/api/sales/auth/login/", {"username": "prathap_t", "password": "Prath@p123"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["user"]["app_role"], "PRATHAP")
        self.assertTrue(res.data["token"])
        res = client.post("/api/sales/auth/login/", {"username": "salesadmin", "password": "Adm1n@Pass!"},
                          format="json")
        self.assertEqual(res.data["user"]["app_role"], "ADMIN")

    def test_login_rejects_bad_password_and_non_sales_user(self):
        client = APIClient()
        self.assertEqual(client.post("/api/sales/auth/login/", {"username": "prathap_t", "password": "x"},
                                     format="json").status_code, 401)
        self.assertEqual(client.post("/api/sales/auth/login/", {"username": "operator", "password": "Op3rator!"},
                                     format="json").status_code, 403)

    def test_expired_token_is_rejected(self):
        client = self.client_for(self.prathap)
        Token.objects.filter(user=self.prathap).update(created=timezone.now() - timedelta(hours=13))
        self.assertEqual(client.get("/api/sales/auth/me/").status_code, 401)

    def test_unauthenticated_blocked(self):
        self.assertIn(APIClient().get("/api/sales/dashboard/").status_code, (401, 403))

    def test_logout_deletes_token(self):
        client = self.client_for(self.prathap)
        self.assertEqual(client.post("/api/sales/auth/logout/").status_code, 200)
        self.assertFalse(Token.objects.filter(user=self.prathap).exists())

    def test_web_session_login_still_works(self):
        res = self.client.post("/api/auth/login/", {"username": "prathap_t", "password": "Prath@p123"})
        self.assertEqual(res.status_code, 200)


# ---------------------------------------------------------------------------
# Mill master
# ---------------------------------------------------------------------------

class MillApiTests(SalesTestBase):
    def test_add_customer_creates_central_mill_and_contact(self):
        client = self.client_for(self.prathap)
        res = client.post("/api/sales/mills/", {
            "name": "New Mill", "address": "Addr", "gstin": "33aabcn1234d1z5", "primary_contact": "Anil",
            "contact_number": "12345", "designation": "Spinning Master", "ring_profile": "AW",
        }, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        mill = Mill.objects.get(name="New Mill")
        self.assertEqual(mill.gstin, "33AABCN1234D1Z5")
        self.assertEqual(mill.contacts.get().name, "Anil")
        # Immediately usable by leads/search.
        self.assertEqual(client.get("/api/sales/mills/?search=New").data["results"][0]["name"], "New Mill")
        self.assertTrue(Notification.objects.filter(recipient=self.admin, kind="mill_created").exists())

    def test_duplicate_and_bad_gstin_rejected(self):
        client = self.client_for(self.prathap)
        self.assertEqual(client.post("/api/sales/mills/", {"name": "test spinning mills"}, format="json").status_code,
                         400)
        self.assertEqual(client.post("/api/sales/mills/", {"name": "Z", "gstin": "123"}, format="json").status_code,
                         400)

    def test_only_admin_deactivates(self):
        self.assertEqual(self.client_for(self.prathap).delete(f"/api/sales/mills/{self.mill.pk}/").status_code, 403)
        self.assertEqual(self.client_for(self.admin).delete(f"/api/sales/mills/{self.mill.pk}/").status_code, 204)
        self.mill.refresh_from_db()
        self.assertFalse(self.mill.is_active)

    def test_mill_detail_has_view_mill_details_fields(self):
        res = self.client_for(self.prathap).get(f"/api/sales/mills/{self.mill.pk}/")
        self.assertEqual(res.data["address"], "1 Main Rd")
        self.assertEqual(res.data["gstin"], "33AABCS1234D1Z5")
        self.assertEqual(res.data["contacts"][0]["designation"], "Production Manager")


# ---------------------------------------------------------------------------
# Lead stage 1 + lifecycle
# ---------------------------------------------------------------------------

class LeadWorkflowTests(SalesTestBase):
    def test_stage1_wizard_save_next_and_complete(self):
        client = self.client_for(self.prathap)
        res = client.post("/api/sales/leads/", {"mill": str(self.mill.pk), "contact": str(self.contact.pk),
                                                "visit_date": str(self.today)}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        lead_id = res.data["id"]
        self.assertEqual(res.data["status"], "draft")

        # Next on screen 2 with nothing filled -> field errors, nothing lost.
        res = client.post(f"/api/sales/leads/{lead_id}/stage1/", {"step": 2, "validate": True, "make": "LMW"},
                          format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("total_spindles", res.data["errors"])
        self.assertEqual(Lead.objects.get(pk=lead_id).make, "LMW")  # draft kept

        res = client.post(f"/api/sales/leads/{lead_id}/stage1/", {
            "step": 2, "validate": True, "total_spindles": 25000, "frame_details": "LR6", "make": "LMW",
            "ring_make": "Rieter", "ring_profile": "CR", "speed": "18000", "count": "40s", "fibre_type": "Cotton",
        }, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["stage1_step"], 3)

        res = client.post(f"/api/sales/leads/{lead_id}/stage1/", {
            "step": 3, "validate": True, "existing_traveller_used": "Competitor", "brand": "Other",
            "wire_section": "Flat", "surface_finish": "Nickel", "traveller_number": "14/0",
            "frequency_of_change": "15 Days", "sample_quantity": "1000", "technical_remarks": "x" * 500,
        }, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        too_long = client.post(f"/api/sales/leads/{lead_id}/stage1/", {"step": 3, "technical_remarks": "x" * 501},
                               format="json")
        self.assertEqual(too_long.status_code, 400)

        res = client.post(f"/api/sales/leads/{lead_id}/complete-stage1/", {"next_action": "followup"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        lead = Lead.objects.get(pk=lead_id)
        self.assertEqual(lead.status, "open")
        self.assertEqual(lead.stage, "initial_introduction")
        self.assertEqual(lead.next_action, "followup")
        self.assertEqual(lead.reminder_date, self.today + timedelta(days=15))
        # Stage 1 is recorded as the Initial Introduction visit of the journey.
        visit = Visit.objects.get(lead=lead)
        self.assertEqual(visit.purpose, "initial_introduction")
        self.assertEqual(visit.next_followup_date, self.today + timedelta(days=15))
        reminder = Reminder.objects.get(lead=lead, status="pending")
        self.assertEqual(reminder.reminder_type, "lead_followup")
        self.assertEqual(reminder.assigned_to, self.prathap)
        self.assertFalse(reminder.is_overridden)
        # Visit data flows to the central mill master.
        self.mill.refresh_from_db()
        self.assertEqual(self.mill.total_spindles, 25000)
        self.assertEqual(self.mill.ring_profile, "CR")

    def test_complete_stage1_requires_all_screens(self):
        lead = Lead.objects.create(mill=self.mill, assigned_to=self.prathap)
        res = self.client_for(self.prathap).post(f"/api/sales/leads/{lead.pk}/complete-stage1/",
                                                 {"next_action": "followup"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("visit_date", res.data)

    def test_no_further_action_closes_without_reminder(self):
        lead = self.stage1_lead()
        services.complete_stage1(lead, self.prathap, "no_further_action")
        lead.refresh_from_db()
        self.assertEqual(lead.status, "closed")
        self.assertIsNone(lead.reminder_date)
        self.assertFalse(Reminder.objects.filter(lead=lead).exists())

    def test_override_reminder_and_history_preserved(self):
        lead = self.stage1_lead()
        chosen = self.today + timedelta(days=3)
        services.complete_stage1(lead, self.prathap, "followup", reminder_override=chosen)
        first = Reminder.objects.get(lead=lead)
        self.assertTrue(first.is_overridden)
        self.assertEqual(first.reminder_date, chosen)
        self.assertEqual(first.default_date, self.today + timedelta(days=15))
        # Mill asks for another visit: follow-up again -> new reminder, old kept.
        services.advance_lead(lead, self.prathap, "followup")
        first.refresh_from_db()
        self.assertEqual(first.status, "superseded")
        self.assertEqual(Reminder.objects.filter(lead=lead).count(), 2)
        self.assertEqual(Reminder.objects.filter(lead=lead, status="pending").count(), 1)
        self.assertEqual(LeadEvent.objects.filter(lead=lead).count(), 2)

    def test_invalid_transition_rejected(self):
        lead = self.stage1_lead()
        services.complete_stage1(lead, self.prathap, "trial")
        services.advance_lead(lead, self.prathap, "trial_followup", step="trial")
        client = self.client_for(self.prathap)
        # Cannot go back to an earlier step, nor pick an earlier step as next action.
        res = client.post(f"/api/sales/leads/{lead.pk}/advance/",
                          {"step": "initial_introduction", "next_action": "followup"}, format="json")
        self.assertEqual(res.status_code, 400)
        res = client.post(f"/api/sales/leads/{lead.pk}/advance/", {"next_action": "requirement_discussion"},
                          format="json")
        self.assertEqual(res.status_code, 400)

    def test_prathap_sees_only_own_leads_admin_sees_all(self):
        other = User.objects.create_user("exec2", password="x")
        UserRole.objects.create(user=other, role=Role.objects.get(code="sales_executive"))
        self.stage1_lead(user=other)
        mine = self.stage1_lead()
        res = self.client_for(self.prathap).get("/api/sales/leads/")
        self.assertEqual([r["id"] for r in res.data["results"]], [str(mine.pk)])
        self.assertEqual(self.client_for(self.admin).get("/api/sales/leads/").data["count"], 2)


class TrialAndOrderLifecycleTests(SalesTestBase):
    def _trial(self, client, lead, **extra):
        payload = {"lead": str(lead.pk), "product_type": "U1 UL UDR 14/0", "batch": "970", "quantity": "1200 * 2",
                   "finish": self.finish.pk, "trial_start_date": str(self.today), "delivery_mode": "Courier"}
        payload.update(extra)
        return client.post("/api/sales/trials/", payload, format="json")

    def test_full_cycle_with_repeat_trials_and_order(self):
        client = self.client_for(self.prathap)
        admin = self.client_for(self.admin)
        lead = self.stage1_lead()
        services.complete_stage1(lead, self.prathap, "trial")

        res = self._trial(client, lead)
        self.assertEqual(res.status_code, 201, res.content)
        t1 = res.data["id"]
        self.assertEqual(res.data["trial_no"], 1)
        self.assertTrue(Notification.objects.filter(recipient=self.admin, kind="trial_created").exists())

        lead.refresh_from_db()
        self.assertEqual(lead.stage, "trial")
        self.assertEqual(lead.next_action, "trial_followup")
        self.assertEqual(Reminder.objects.get(lead=lead, status="pending").reminder_type, "trial_followup")

        # Admin reviews, Prathap marks in progress.
        self.assertEqual(admin.post(f"/api/sales/trials/{t1}/set-status/", {"status": "trial_pending"},
                                    format="json").status_code, 200)
        self.assertEqual(client.post(f"/api/sales/trials/{t1}/set-status/", {"status": "trial_in_progress"},
                                     format="json").status_code, 200)

        # Trial 1 fails -> Trial 2 -> fails -> Trial 3 -> successful.
        client.post(f"/api/sales/trials/{t1}/set-status/", {"status": "trial_failed"}, format="json")
        res = self._trial(client, lead, previous_trial=t1)
        self.assertEqual(res.status_code, 201, res.content)
        t2 = res.data["id"]
        self.assertEqual(res.data["trial_no"], 2)
        client.post(f"/api/sales/trials/{t2}/set-status/", {"status": "trial_in_progress"}, format="json")
        client.post(f"/api/sales/trials/{t2}/set-status/", {"status": "trial_failed"}, format="json")
        t3 = self._trial(client, lead, previous_trial=t2).data["id"]
        client.post(f"/api/sales/trials/{t3}/set-status/", {"status": "trial_in_progress"}, format="json")
        res = client.post(f"/api/sales/trials/{t3}/set-status/", {"status": "trial_successful"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)

        trials = TrialOrder.objects.filter(lead=lead).order_by("trial_no")
        self.assertEqual([t.trial_no for t in trials], [1, 2, 3])
        self.assertEqual([t.status for t in trials], ["repeat_trial", "repeat_trial", "trial_successful"])
        lead.refresh_from_db()
        self.assertEqual(lead.stage, "trial_followup")
        self.assertEqual(lead.next_action, "order_discussion")
        self.assertEqual(lead.reminder_date, self.today + timedelta(days=15))

        # Order placed -> admin notified -> monthly repeat-order reminder.
        res = client.post("/api/sales/orders/", {
            "mill": str(self.mill.pk), "lead": str(lead.pk), "trial": t3, "traveller_type": self.tt.pk,
            "traveller_no": self.tn.pk, "finish": self.finish.pk, "required_m": "5000", "order_type": "stock",
        }, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.data["status"], "placed")
        self.assertTrue(Notification.objects.filter(recipient=self.admin, kind="order_created").exists())
        lead.refresh_from_db()
        self.assertEqual(lead.stage, "order_received")
        self.assertEqual(lead.next_action, "repeat_order_followup")
        pending = Reminder.objects.get(lead=lead, status="pending")
        self.assertEqual(pending.reminder_type, "repeat_order")
        self.assertEqual(pending.reminder_date, rules.add_months(self.today, 1))
        self.assertEqual(TrialOrder.objects.get(pk=t3).status, "order_placed")

        # Completing the monthly reminder schedules the next month.
        services.complete_reminder(pending, self.prathap)
        self.assertEqual(Reminder.objects.filter(lead=lead, status="pending", reminder_type="repeat_order").count(), 1)

        # Admin verifies the order; Prathap is told.
        order_id = res.data["id"]
        self.assertEqual(client.post(f"/api/sales/orders/{order_id}/set-status/", {"status": "confirmed"},
                                     format="json").status_code, 403)
        self.assertEqual(admin.post(f"/api/sales/orders/{order_id}/set-status/", {"status": "confirmed"},
                                    format="json").status_code, 200)
        self.assertTrue(Notification.objects.filter(recipient=self.prathap, kind="order_status").exists())

        timeline = [e.stage for e in LeadEvent.objects.filter(lead=lead)]
        self.assertEqual(timeline[0], "initial_introduction")
        self.assertIn("trial", timeline)
        self.assertIn("trial_followup", timeline)
        self.assertEqual(timeline[-1], "order_received")

    def test_trial_validation(self):
        lead = self.stage1_lead()
        services.complete_stage1(lead, self.prathap, "trial")
        res = self._trial(self.client_for(self.prathap), lead, delivery_mode="Truck", batch="")
        self.assertEqual(res.status_code, 400)
        self.assertIn("delivery_mode", res.data)
        self.assertIn("batch", res.data)

    def test_only_admin_reviews_trial(self):
        lead = self.stage1_lead()
        services.complete_stage1(lead, self.prathap, "trial")
        t = self._trial(self.client_for(self.prathap), lead).data["id"]
        res = self.client_for(self.prathap).post(f"/api/sales/trials/{t}/set-status/", {"status": "trial_pending"},
                                                 format="json")
        self.assertEqual(res.status_code, 403)


class StockAndPhoneEnquiryTests(SalesTestBase):
    def test_out_of_stock_then_new_requirement_order(self):
        client = self.client_for(self.prathap)
        res = client.post("/api/sales/stock-check/", {"traveller_type_id": self.tt.pk, "traveller_no_id": self.tn.pk,
                                                      "finish_id": self.finish.pk, "required_m": "1000",
                                                      "mill": str(self.mill.pk)}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["stock_status"], "OUT_OF_STOCK")
        self.assertEqual(Decimal(res.data["available_kg"]), Decimal("0"))
        self.assertEqual(res.data["brand"], "Rover")
        enquiry = StockEnquiry.objects.get(pk=res.data["enquiry_id"])
        self.assertFalse(enquiry.is_resolved)
        dash = self.client_for(self.admin).get("/api/sales/dashboard/").data
        self.assertEqual(dash["counts"]["pending_stock_enquiries"], 1)

        res = client.post("/api/sales/orders/", {
            "mill": str(self.mill.pk), "traveller_type": self.tt.pk, "traveller_no": self.tn.pk,
            "finish": self.finish.pk, "required_m": "1000", "order_type": "new_requirement",
            "stock_enquiry": str(enquiry.pk),
        }, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.data["stock_status_at_order"], "OUT_OF_STOCK")
        enquiry.refresh_from_db()
        self.assertTrue(enquiry.is_resolved)
        note = Notification.objects.get(recipient=self.admin, kind="order_created")
        self.assertIn("Test Spinning Mills", note.body)
        admin_orders = self.client_for(self.admin).get("/api/sales/orders/").data["results"]
        self.assertEqual(admin_orders[0]["created_by"]["username"], "prathap_t")

    def lot_for(self, traveller_type, traveller_no, finish, serial):
        """A production lot carrying a completed Rolling batch: it exists in
        Process 1-4 but is not in Finished Goods until an FG row is added."""
        if not hasattr(self, "_order"):
            uom = UnitOfMeasure.objects.create(code="KG", name="Kilogram")
            material = MaterialMaster.objects.create(material_code="RM-1", name="Wire", unit_of_measure=uom)
            self._product = ProductMaster.objects.create(product_code="FG-1", name="Traveller",
                                                         unit_of_measure=uom, raw_material=material)
            self._order = ProductionOrder.objects.create(product=self._product, planned_quantity=Decimal("1000"))
        batch = RollingBatch.objects.create(
            wire_serial=serial, traveller_type=traveller_type, traveller_no=traveller_no, finish=finish,
            wire_diameter_mm=Decimal("0.93"), f_thickness_mm=Decimal("0.41"), f_width_mm=Decimal("1.78"),
            required_box=1, wire_weight_issued_kg=Decimal("500"), status="Completed",
            finished_weight_kg=Decimal("500"), completed_at=timezone.now(),
        )
        return ProductionLot.objects.create(production_order=self._order, quantity=Decimal("500"),
                                            source_rolling_batch=batch)

    def fg(self, lot, kg, status="available"):
        return FinishedGoodsStock.objects.create(product=self._product, lot=lot, accepted_quantity=Decimal(kg),
                                                 quality_approved=status == "available", status=status)

    def test_in_stock_from_finished_goods(self):
        self.fg(self.lot_for(self.tt, self.tn, self.finish, "WS1"), "30")
        self.fg(self.lot_for(self.tt, self.tn, self.finish, "WS2"), "20")
        result = services.check_stock(traveller_type_id=self.tt.pk, traveller_no_id=self.tn.pk,
                                      finish_id=self.finish.pk, required_m="10", record=False)
        # No raw-material mapping -> weight cannot be compared, so never claims IN STOCK.
        self.assertEqual(result["available_kg"], Decimal("50"))
        self.assertEqual(result["stock_status"], "PARTIALLY_AVAILABLE")
        self.assertFalse(result["has_mapping"])
        self.assertNotIn("raw_material", result)

    def test_options_list_only_available_finished_goods(self):
        other_no = TravellerNo.objects.create(code="2/0")
        hold_no = TravellerNo.objects.create(code="3/0")
        rejected_no = TravellerNo.objects.create(code="4/0")
        other_finish = SurfaceFinish.objects.create(finish_name="Indigo")
        self.fg(self.lot_for(self.tt, self.tn, self.finish, "WS1"), "30")
        self.fg(self.lot_for(self.tt, self.tn, self.finish, "WS2"), "20")
        self.fg(self.lot_for(self.tt, self.tn, other_finish, "WS3"), "0")  # nothing left
        self.lot_for(self.tt, other_no, self.finish, "WS4")  # Rolling..Finishing only, never reached FG
        self.fg(self.lot_for(self.tt, hold_no, self.finish, "WS5"), "40", status="hold")
        self.fg(self.lot_for(self.tt, rejected_no, self.finish, "WS6"), "40", status="rejected")

        res = self.client_for(self.prathap).get("/api/sales/stock-check/options/")
        self.assertEqual(res.status_code, 200, res.content)
        rows = res.data["results"]
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual((rows[0]["traveller_type_id"], rows[0]["traveller_no_id"], rows[0]["finish_id"]),
                         (self.tt.pk, self.tn.pk, self.finish.pk))
        self.assertEqual(rows[0]["traveller_type_name"], "U1 UL UDR")
        self.assertEqual(rows[0]["traveller_no_code"], "14/0")
        self.assertEqual(rows[0]["finish_name"], "Nickel + T")
        self.assertEqual(Decimal(rows[0]["available_kg"]), Decimal("50"))

        # The check agrees with the list: hold/rejected/WIP products count as zero.
        for number in (other_no, hold_no, rejected_no):
            result = services.check_stock(traveller_type_id=self.tt.pk, traveller_no_id=number.pk,
                                          required_m="10", record=False)
            self.assertEqual(result["available_kg"], Decimal("0"), number.code)
            self.assertEqual(result["stock_status"], "OUT_OF_STOCK")

    def test_options_empty_and_permissions(self):
        res = self.client_for(self.prathap).get("/api/sales/stock-check/options/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["results"], [])
        self.assertEqual(self.client_for(self.outsider).get("/api/sales/stock-check/options/").status_code, 403)

    def test_stock_check_response_has_no_raw_material(self):
        res = self.client_for(self.prathap).post("/api/sales/stock-check/", {
            "traveller_type_id": self.tt.pk, "traveller_no_id": self.tn.pk, "required_m": "10"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertNotIn("raw_material", res.data)

    def test_stock_check_validation(self):
        res = self.client_for(self.prathap).post("/api/sales/stock-check/", {"traveller_type_id": "x",
                                                                            "required_m": "-1"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("traveller_type_id", res.data)
        self.assertIn("required_m", res.data)


class ActivityAndReminderTests(SalesTestBase):
    def test_prathap_activity_without_time(self):
        client = self.client_for(self.prathap)
        res = client.post("/api/sales/activities/", {
            "activity_type": "visit", "mill": str(self.mill.pk), "date": str(self.today),
            "purpose": "Discuss trial", "priority": "normal",
        }, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertIsNone(res.data["time"])
        self.assertEqual(res.data["assigned_to"]["username"], "prathap_t")
        self.assertEqual(client.get("/api/sales/activities/?bucket=today").data["count"], 1)

    def test_date_and_purpose_required(self):
        res = self.client_for(self.prathap).post("/api/sales/activities/", {
            "activity_type": "call", "mill": str(self.mill.pk)}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("date", res.data)
        self.assertIn("purpose", res.data)

    def test_admin_assigns_activity_to_prathap(self):
        res = self.client_for(self.admin).post("/api/sales/activities/", {
            "activity_type": "meeting", "mill": str(self.mill.pk), "date": str(self.today + timedelta(days=2)),
            "purpose": "Price negotiation", "assigned_to_id": self.prathap.pk, "reminder_days_before": 1,
        }, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertTrue(Notification.objects.filter(recipient=self.prathap, kind="activity_assigned").exists())
        mine = self.client_for(self.prathap).get("/api/sales/activities/?bucket=upcoming").data
        self.assertEqual(mine["count"], 1)
        reminder = Reminder.objects.get(entity_type="Activity")
        self.assertEqual(reminder.reminder_date, self.today + timedelta(days=1))

    def test_prathap_cannot_assign_to_others(self):
        res = self.client_for(self.prathap).post("/api/sales/activities/", {
            "activity_type": "call", "mill": str(self.mill.pk), "date": str(self.today), "purpose": "x",
            "assigned_to_id": self.admin.pk}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_overdue_and_complete(self):
        activity = services.create_activity(user=self.prathap, activity_type="call", mill=self.mill,
                                            date=self.today - timedelta(days=2), purpose="Call back")
        self.assertEqual(activity.display_status, "overdue")
        client = self.client_for(self.prathap)
        self.assertEqual(client.get("/api/sales/activities/?bucket=overdue").data["count"], 1)
        res = client.post(f"/api/sales/activities/{activity.pk}/complete/", {"outcome": "Done"}, format="json")
        self.assertEqual(res.data["status"], "completed")

    def test_reminder_reschedule_keeps_history_and_notifies(self):
        lead = self.stage1_lead()
        services.complete_stage1(lead, self.prathap, "followup")
        reminder = Reminder.objects.get(lead=lead)
        client = self.client_for(self.prathap)
        new_date = self.today + timedelta(days=2)
        res = client.post(f"/api/sales/reminders/{reminder.pk}/reschedule/", {"reminder_date": str(new_date)},
                          format="json")
        self.assertEqual(res.status_code, 200, res.content)
        reminder.refresh_from_db()
        self.assertEqual(reminder.status, "superseded")
        self.assertEqual(Reminder.objects.filter(lead=lead).count(), 2)
        # Due reminders become notifications once.
        Reminder.objects.filter(lead=lead, status="pending").update(reminder_date=self.today - timedelta(days=1))
        self.assertEqual(services.generate_due_reminder_notifications(self.prathap), 1)
        self.assertEqual(services.generate_due_reminder_notifications(self.prathap), 0)
        self.assertEqual(client.get("/api/sales/notifications/unread-count/").data["unread"], 1)


class DashboardSearchMonitoringTests(SalesTestBase):
    def test_role_based_dashboard(self):
        prathap = self.client_for(self.prathap).get("/api/sales/dashboard/").data
        admin = self.client_for(self.admin).get("/api/sales/dashboard/").data
        self.assertNotIn("total_mills", prathap["counts"])
        self.assertEqual(admin["counts"]["total_mills"], 1)
        self.assertEqual(prathap["user"]["app_role"], "PRATHAP")

    def test_search(self):
        lead = self.stage1_lead()
        res = self.client_for(self.prathap).get("/api/sales/search/?q=Spinning")
        self.assertEqual(res.data["mills"][0]["name"], "Test Spinning Mills")
        res = self.client_for(self.prathap).get(f"/api/sales/search/?q={lead.number}")
        self.assertEqual(res.data["leads"][0]["number"], lead.number)
        res = self.client_for(self.prathap).get("/api/sales/search/?q=14/0")
        self.assertTrue(res.data["leads"])

    def test_monitoring_admin_only(self):
        self.assertEqual(self.client_for(self.prathap).get("/api/sales/monitoring/").status_code, 403)
        res = self.client_for(self.admin).get("/api/sales/monitoring/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["people"][0]["user"]["username"], "prathap_t")

    def test_masters_endpoint(self):
        res = self.client_for(self.prathap).get("/api/sales/masters/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("delivery_mode", res.data["values"])
        self.assertEqual(res.data["default_reminder_days"], 15)


# ---------------------------------------------------------------------------
# Visit Recording / Sales Journey
# ---------------------------------------------------------------------------

class VisitJourneyTests(SalesTestBase):
    def visit(self, client, purpose, next_action, **extra):
        payload = {"mill": str(self.mill.pk), "contact": str(self.contact.pk), "visit_date": str(self.today),
                   "visit_time": "10:00", "visit_type": "mill_visit", "purpose": purpose, "next_action": next_action,
                   "summary": f"{purpose} done", "details": {}}
        payload.update(extra)
        return client.post("/api/sales/visits/", payload, format="json")

    def test_full_ten_step_journey_is_tracked(self):
        client = self.client_for(self.prathap)
        res = self.visit(client, "initial_introduction", "requirement_discussion",
                         people_met="Ramesh Kumar (Production Manager)", outcome="Interest shown")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.data["step_index"], 1)
        self.assertEqual(res.data["next_followup_date"], str(self.today + timedelta(days=15)))
        lead = Lead.objects.get(mill=self.mill)
        self.assertEqual((lead.stage, lead.status, lead.assigned_to), ("initial_introduction", "open", self.prathap))
        self.assertEqual(Reminder.objects.get(lead=lead, status="pending").reminder_type, "lead_followup")

        steps = [
            ("requirement_discussion", "sample_requested",
             {"details": {"traveller_type": "Ring Traveller", "size_od": "42 mm", "quantity": "20,000 pieces/month",
                          "application": "Rieter G35", "current_supplier": "XYZ", "decision_time": "Within 1 month"}}),
            ("sample_requested", "sample_delivered",
             {"details": {"sample_requested": "Ring Traveller 42 mm", "quantity_requested": "10 Pieces",
                          "required_by": str(self.today + timedelta(days=5)), "trial_plan": "Test in Rieter G35"}}),
            ("sample_delivered", "trial",
             {"details": {"sample_details": "Ring Traveller 42 mm", "quantity_delivered": "10 Pieces",
                          "delivered_to": "Rajesh Kumar", "delivery_mode": "By Hand"}}),
            ("trial", "trial_followup",
             {"details": {"trial_status": "Trial In Progress", "trial_started_on": str(self.today),
                          "trial_machine": "Rieter G35", "trial_performance": "Running good"},
              "trial": {"product_type": "U1 UL UDR 14/0", "batch": "970", "quantity": "1200 * 2",
                        "finish": self.finish.pk, "delivery_mode": "Direct"}}),
            ("trial_followup", "order_discussion",
             {"details": {"trial_result": "successful", "customer_feedback": "Performance is good"}}),
            ("order_discussion", "order_received",
             {"details": {"order_quantity": "20,000 pieces/month", "rate_discussed": "12.50", "payment_terms": "30 Days"}}),
            ("order_received", "repeat_order_followup",
             {"order": {"po_number": "PO/ABC/260915", "po_date": str(self.today), "order_quantity": "20000",
                        "rate": "12.50", "delivery_date": str(self.today + timedelta(days=15)),
                        "traveller_type": self.tt.pk, "traveller_no": self.tn.pk, "finish": self.finish.pk}}),
            ("repeat_order_followup", "repeat_order",
             {"details": {"consumption_status": "First order consumed", "reorder_requirement": "Yes"}}),
            ("repeat_order", "repeat_order_followup",
             {"order": {"po_number": "PO/ABC/261015", "order_quantity": "20000", "rate": "12.50",
                        "traveller_type": self.tt.pk, "traveller_no": self.tn.pk, "finish": self.finish.pk}}),
        ]
        for purpose, next_action, extra in steps:
            res = self.visit(client, purpose, next_action, **extra)
            self.assertEqual(res.status_code, 201, (purpose, res.content))

        lead.refresh_from_db()
        self.assertEqual(lead.stage, "repeat_order")
        self.assertEqual(lead.next_action, "repeat_order_followup")
        # Monthly follow-up after an order.
        self.assertEqual(lead.reminder_date, rules.add_months(self.today, 1))
        self.assertEqual(Reminder.objects.filter(lead=lead, status="pending").count(), 1)
        self.assertEqual(Visit.objects.filter(lead=lead).count(), 10)

        trial = TrialOrder.objects.get(lead=lead)
        self.assertEqual(trial.status, "order_placed")  # successful, then the order was placed on it
        orders = list(SalesOrder.objects.filter(lead=lead).order_by("created_at"))
        self.assertEqual([o.order_type for o in orders], ["new_requirement", "repeat"])
        self.assertEqual(orders[0].po_number, "PO/ABC/260915")
        self.assertEqual(orders[0].order_value, Decimal("250000.00"))
        self.assertEqual(Visit.objects.get(purpose="order_received").order, orders[0])
        self.assertTrue(Notification.objects.filter(recipient=self.admin, kind="order_created").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.admin, kind="visit_recorded").exists())

        journey = client.get(f"/api/sales/mills/{self.mill.pk}/journey/").data
        self.assertTrue(all(step["done"] for step in journey["steps"]))
        self.assertEqual(journey["current"], "repeat_order")
        self.assertEqual(len(journey["visits"]), 10)
        self.assertEqual(journey["mill"]["customer_status"], "active")
        self.assertEqual(journey["mill"]["visit_count"], 10)

        lead_data = client.get(f"/api/sales/leads/{lead.pk}/").data
        self.assertEqual(len(lead_data["visits"]), 10)
        self.assertEqual(lead_data["journey"]["current"], "repeat_order")

    def test_default_and_override_followup_date(self):
        client = self.client_for(self.prathap)
        chosen = self.today + timedelta(days=4)
        res = self.visit(client, "initial_introduction", "followup", next_followup_date=str(chosen))
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.data["next_followup_date"], str(chosen))
        self.assertTrue(res.data["followup_overridden"])
        reminder = Reminder.objects.get(status="pending")
        self.assertEqual((reminder.reminder_date, reminder.default_date), (chosen, self.today + timedelta(days=15)))
        past = self.visit(client, "initial_introduction", "followup",
                          next_followup_date=str(self.today - timedelta(days=1)))
        self.assertEqual(past.status_code, 400)
        self.assertIn("next_followup_date", past.data)

    def test_validation_and_order_of_steps(self):
        client = self.client_for(self.prathap)
        res = self.visit(client, "initial_introduction", "followup", summary="")
        self.assertEqual(res.status_code, 400)
        self.assertIn("summary", res.data)
        res = self.visit(client, "order_received", "repeat_order_followup", order={"po_number": "PO1"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("order_quantity", res.data)
        self.assertIn("traveller_type", res.data)
        self.assertFalse(SalesOrder.objects.exists())
        self.assertFalse(Visit.objects.exists())  # nothing half-saved

        self.assertEqual(self.visit(client, "sample_requested", "sample_delivered",
                                    details={"sample_requested": "42 mm", "trial_plan": "G35"}).status_code, 201)
        back = self.visit(client, "initial_introduction", "followup")
        self.assertEqual(back.status_code, 400)
        self.assertIn("purpose", back.data)
        bad_next = self.visit(client, "sample_delivered", "requirement_discussion",
                              details={"sample_details": "42 mm", "quantity_delivered": "10"})
        self.assertEqual(bad_next.status_code, 400)
        self.assertIn("next_action", bad_next.data)
        future = self.visit(client, "sample_delivered", "trial", visit_date=str(self.today + timedelta(days=1)),
                            details={"sample_details": "42 mm", "quantity_delivered": "10"})
        self.assertEqual(future.status_code, 400)

    def test_no_further_action_closes_and_next_visit_starts_new_journey(self):
        client = self.client_for(self.prathap)
        self.assertEqual(self.visit(client, "initial_introduction", "no_further_action").status_code, 201)
        first = Lead.objects.get(mill=self.mill)
        self.assertEqual(first.status, "closed")
        self.assertFalse(Reminder.objects.filter(lead=first, status="pending").exists())
        self.assertEqual(self.visit(client, "initial_introduction", "followup").status_code, 201)
        self.assertEqual(Lead.objects.filter(mill=self.mill).count(), 2)

    def test_started_from_planned_activity_completes_it(self):
        client = self.client_for(self.prathap)
        act = client.post("/api/sales/activities/", {
            "activity_type": "visit", "mill": str(self.mill.pk), "date": str(self.today), "purpose": "Intro visit",
        }, format="json").data
        res = self.visit(client, "initial_introduction", "followup", activity=act["id"])
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(Activity.objects.get(pk=act["id"]).status, "completed")
        plan = client.get("/api/sales/today-plan/").data
        self.assertEqual(plan["visits"], {"completed": 1, "planned": 1})
        self.assertEqual(plan["recorded_visits"], 1)
        self.assertEqual(len(plan["activities"]), 1)

    def test_order_from_orders_tab_is_tracked_on_the_journey(self):
        client = self.client_for(self.prathap)
        payload = {"mill": str(self.mill.pk), "traveller_type": self.tt.pk, "traveller_no": self.tn.pk,
                   "finish": self.finish.pk, "po_number": "PO-9", "order_quantity": "5000", "rate": "10"}
        res = client.post("/api/sales/orders/", payload, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.data["order_value"], "50000.00")
        lead = Lead.objects.get(mill=self.mill)
        self.assertEqual((lead.stage, lead.next_action), ("order_received", "repeat_order_followup"))
        res = client.post("/api/sales/orders/", payload, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.data["order_type"], "repeat")
        lead.refresh_from_db()
        self.assertEqual(lead.stage, "repeat_order")
        no_qty = client.post("/api/sales/orders/", {**payload, "order_quantity": ""}, format="json")
        self.assertEqual(no_qty.status_code, 400)

    def test_customers_list_stats_and_dashboard(self):
        client = self.client_for(self.prathap)
        Mill.objects.create(name="Prospect Mills", city="Salem")
        self.visit(client, "order_received", "repeat_order_followup",
                   order={"po_number": "PO-1", "order_quantity": "100", "traveller_type": self.tt.pk,
                          "traveller_no": self.tn.pk, "finish": self.finish.pk})
        stats = client.get("/api/sales/mills/stats/").data
        self.assertEqual((stats["total"], stats["active"], stats["prospects"], stats["visited_this_month"]),
                         (2, 1, 1, 1))
        rows = client.get("/api/sales/mills/?sort=last_visited").data["results"]
        self.assertEqual(rows[0]["name"], "Test Spinning Mills")
        self.assertEqual(rows[0]["visit_count"], 1)
        self.assertEqual(rows[0]["journey_stage"], "order_received")
        active = client.get("/api/sales/mills/?status=active").data["results"]
        self.assertEqual([r["name"] for r in active], ["Test Spinning Mills"])
        prospects = client.get("/api/sales/mills/?status=prospect").data["results"]
        self.assertEqual([r["name"] for r in prospects], ["Prospect Mills"])
        dash = client.get("/api/sales/dashboard/").data
        groups = {g["key"]: g["count"] for g in dash["pipeline_groups"]}
        self.assertEqual(groups["orders_expected"], 1)
        self.assertEqual(dash["counts"]["month"]["visits"], 1)
        self.assertEqual(dash["repeat_order_opportunities"][0]["mill_name"], "Test Spinning Mills")

    def test_masters_expose_journey(self):
        data = self.client_for(self.prathap).get("/api/sales/masters/").data
        self.assertEqual([s["code"] for s in data["journey_steps"]], rules.JOURNEY)
        self.assertEqual(data["suggested_next"]["trial"], "trial_followup")
        self.assertIn("mill_visit", [v["code"] for v in data["visit_types"]])
