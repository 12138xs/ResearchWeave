from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client, TestCase


class AuthCsrfProtectionTests(TestCase):
    def csrf_token_for(self, client: Client) -> str:
        client.get("/api/me/")
        return client.cookies["csrftoken"].value

    def test_login_rejects_missing_csrf_token_when_checks_are_enforced(self) -> None:
        get_user_model().objects.create_user(username="member", password="member-password")
        client = Client(enforce_csrf_checks=True)

        response = client.post(
            "/api/auth/login/",
            {"username": "member", "password": "member-password"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    def test_login_accepts_valid_csrf_token_when_checks_are_enforced(self) -> None:
        get_user_model().objects.create_user(username="member", password="member-password")
        client = Client(enforce_csrf_checks=True)

        response = client.post(
            "/api/auth/login/",
            {"username": "member", "password": "member-password"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self.csrf_token_for(client),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["authenticated"])

    def test_logout_rejects_missing_csrf_token_when_checks_are_enforced(self) -> None:
        get_user_model().objects.create_user(username="member", password="member-password")
        client = Client(enforce_csrf_checks=True)
        client.login(username="member", password="member-password")

        response = client.post("/api/auth/logout/")

        self.assertEqual(response.status_code, 403)

    def test_logout_accepts_valid_csrf_token_when_checks_are_enforced(self) -> None:
        get_user_model().objects.create_user(username="member", password="member-password")
        client = Client(enforce_csrf_checks=True)
        client.login(username="member", password="member-password")

        response = client.post("/api/auth/logout/", HTTP_X_CSRFTOKEN=self.csrf_token_for(client))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["authenticated"])
