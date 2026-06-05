from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase


class AuthApiTests(TestCase):
    def test_me_reports_anonymous_session(self) -> None:
        response = self.client.get("/api/me/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["authenticated"], False)
        self.assertIsNone(payload["user"])
        self.assertIn("csrf_token", payload)

    def test_login_creates_session_and_me_reports_user(self) -> None:
        user = get_user_model().objects.create_user(
            username="trial01",
            password="trial-password",
            email="trial01@research-os.local",
        )

        response = self.client.post(
            "/api/auth/login/",
            {"username": "trial01", "password": "trial-password"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["authenticated"])
        self.assertEqual(payload["user"]["username"], user.username)
        self.assertFalse(payload["user"]["is_staff"])

        me_response = self.client.get("/api/me/")
        self.assertEqual(me_response.status_code, 200)
        self.assertTrue(me_response.json()["authenticated"])

    def test_login_rejects_invalid_credentials(self) -> None:
        get_user_model().objects.create_user(username="trial01", password="trial-password")

        response = self.client.post(
            "/api/auth/login/",
            {"username": "trial01", "password": "wrong"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["authenticated"])

    def test_logout_clears_session(self) -> None:
        get_user_model().objects.create_user(username="trial01", password="trial-password")
        self.client.login(username="trial01", password="trial-password")

        response = self.client.post("/api/auth/logout/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"authenticated": False, "user": None})
        self.assertFalse(self.client.get("/api/me/").json()["authenticated"])
