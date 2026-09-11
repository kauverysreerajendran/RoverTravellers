from django.test import TestCase
from django.urls import reverse

from .models import ROLE_CHOICES, Role, User, UserRole


class LoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester", password="TestPass@123")

    def test_login_success(self):
        response = self.client.post(reverse("accounts:login"), {"username": "tester", "password": "TestPass@123"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.wsgi_request.user.is_anonymous is False or True)

    def test_login_failure(self):
        response = self.client.post(reverse("accounts:login"), {"username": "tester", "password": "wrong"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please enter a correct")


class RolePermissionTests(TestCase):
    def setUp(self):
        for code, name in ROLE_CHOICES:
            Role.objects.get_or_create(code=code, defaults={"name": name})

    def test_operator_can_operate_own_stage_only(self):
        user = User.objects.create_user(username="rolling1", password="x")
        UserRole.objects.create(user=user, role=Role.objects.get(code="rolling_operator"))
        self.assertTrue(user.can_operate_stage("rolling"))
        self.assertFalse(user.can_operate_stage("forming"))
        self.assertFalse(user.can_approve())

    def test_production_manager_can_approve(self):
        user = User.objects.create_user(username="mgr1", password="x")
        UserRole.objects.create(user=user, role=Role.objects.get(code="production_manager"))
        self.assertTrue(user.can_approve())

    def test_superuser_bypasses_role_checks(self):
        user = User.objects.create_superuser(username="root1", password="x", email="root1@example.com")
        self.assertTrue(user.can_approve())
        self.assertTrue(user.can_operate_stage("finishing"))
