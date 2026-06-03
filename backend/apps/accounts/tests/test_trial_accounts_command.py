from __future__ import annotations

import json
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase


class TrialAccountsCommandTests(TestCase):
    def test_dry_run_reports_planned_accounts_without_creating_users(self) -> None:
        output = StringIO()

        call_command("bootstrap_trial_accounts", "--count", "3", "--dry-run", stdout=output)

        payload = json.loads(output.getvalue())
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["planned_count"], 3)
        self.assertEqual(payload["missing_usernames"], ["trial01", "trial02", "trial03"])
        self.assertNotIn("password", output.getvalue().lower())
        self.assertEqual(get_user_model().objects.count(), 0)

    def test_real_run_requires_password_environment_variable(self) -> None:
        with self.assertRaises(CommandError):
            call_command("bootstrap_trial_accounts", "--count", "1", "--password-env", "TRIAL_PASSWORD")

    @patch.dict("os.environ", {"TRIAL_PASSWORD": "change-me-for-trial"}, clear=False)
    def test_real_run_creates_member_accounts_idempotently(self) -> None:
        output = StringIO()

        call_command(
            "bootstrap_trial_accounts",
            "--count",
            "2",
            "--password-env",
            "TRIAL_PASSWORD",
            stdout=output,
        )
        call_command(
            "bootstrap_trial_accounts",
            "--count",
            "2",
            "--password-env",
            "TRIAL_PASSWORD",
            stdout=StringIO(),
        )

        users = list(get_user_model().objects.order_by("username"))
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["created_usernames"], ["trial01", "trial02"])
        self.assertEqual([user.username for user in users], ["trial01", "trial02"])
        self.assertTrue(all(user.is_active for user in users))
        self.assertFalse(any(user.is_staff or user.is_superuser for user in users))
        self.assertTrue(users[0].check_password("change-me-for-trial"))
