from __future__ import annotations

import csv
import json
from io import StringIO
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase


class MemberAccountsCommandTests(TestCase):
    def test_dry_run_reports_usernames_without_creating_users(self) -> None:
        output = StringIO()

        call_command(
            "bootstrap_member_accounts",
            "--usernames",
            "lirongzu,tankaiyao, wangbuxuan ",
            "--dry-run",
            stdout=output,
        )

        payload = json.loads(output.getvalue())
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["planned_count"], 3)
        self.assertEqual(payload["missing_usernames"], ["lirongzu", "tankaiyao", "wangbuxuan"])
        self.assertEqual(get_user_model().objects.count(), 0)
        self.assertNotIn("password", output.getvalue().lower())

    @patch("apps.accounts.management.commands.bootstrap_member_accounts.secrets.token_urlsafe")
    def test_creates_members_and_writes_credentials_without_printing_passwords(self, token_urlsafe) -> None:
        token_urlsafe.side_effect = ["alpha-password", "beta-password"]

        with TemporaryDirectory() as tmpdir:
            credentials_path = Path(tmpdir) / "members.csv"
            output = StringIO()
            call_command(
                "bootstrap_member_accounts",
                "--usernames",
                "lirongzu,tankaiyao",
                "--credentials-output",
                str(credentials_path),
                stdout=output,
            )

            payload = json.loads(output.getvalue())
            rows = list(csv.DictReader(credentials_path.open(encoding="utf-8", newline="")))

        users = list(get_user_model().objects.order_by("username"))
        self.assertEqual(payload["created_usernames"], ["lirongzu", "tankaiyao"])
        self.assertEqual(payload["updated_usernames"], [])
        self.assertEqual([user.username for user in users], ["lirongzu", "tankaiyao"])
        self.assertTrue(all(user.is_active for user in users))
        self.assertFalse(any(user.is_staff or user.is_superuser for user in users))
        self.assertTrue(users[0].check_password("alpha-password"))
        self.assertTrue(users[1].check_password("beta-password"))
        self.assertEqual(
            rows,
            [
                {"username": "lirongzu", "password": "alpha-password"},
                {"username": "tankaiyao", "password": "beta-password"},
            ],
        )
        self.assertNotIn("alpha-password", output.getvalue())
        self.assertNotIn("beta-password", output.getvalue())

    @patch("apps.accounts.management.commands.bootstrap_member_accounts.secrets.token_urlsafe")
    def test_reset_existing_updates_password_and_records_updated_user(self, token_urlsafe) -> None:
        token_urlsafe.return_value = "new-password"
        user = get_user_model().objects.create_user(username="lirongzu", password="old-password")
        output = StringIO()

        with TemporaryDirectory() as tmpdir:
            call_command(
                "bootstrap_member_accounts",
                "--usernames",
                "lirongzu",
                "--credentials-output",
                str(Path(tmpdir) / "members.csv"),
                "--reset-existing",
                stdout=output,
            )

        user.refresh_from_db()
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["created_usernames"], [])
        self.assertEqual(payload["updated_usernames"], ["lirongzu"])
        self.assertTrue(user.check_password("new-password"))

    def test_rejects_empty_username_list(self) -> None:
        with self.assertRaises(CommandError):
            call_command("bootstrap_member_accounts", "--usernames", " , ")
