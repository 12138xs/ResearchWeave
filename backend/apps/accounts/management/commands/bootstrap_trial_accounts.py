from __future__ import annotations

import json
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create deterministic member accounts for a Research OS trial."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--count", type=int, default=10, help="Number of trial accounts to ensure.")
        parser.add_argument("--prefix", default="trial", help="Username prefix.")
        parser.add_argument("--email-domain", default="research-os.local", help="Email domain for trial users.")
        parser.add_argument(
            "--password-env",
            default="RESEARCH_OS_TRIAL_PASSWORD",
            help="Environment variable holding the initial password.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Report planned accounts without writing users.")

    def handle(self, *args, **options) -> None:
        count = options["count"]
        if count <= 0 or count > 100:
            raise CommandError("--count must be between 1 and 100.")

        prefix = options["prefix"].strip()
        if not prefix:
            raise CommandError("--prefix must not be empty.")

        usernames = [f"{prefix}{index:02d}" for index in range(1, count + 1)]
        User = get_user_model()
        existing_usernames = set(User.objects.filter(username__in=usernames).values_list("username", flat=True))
        missing_usernames = [username for username in usernames if username not in existing_usernames]

        if options["dry_run"]:
            self.stdout.write(
                json.dumps(
                    {
                        "dry_run": True,
                        "planned_count": count,
                        "existing_usernames": sorted(existing_usernames),
                        "missing_usernames": missing_usernames,
                        "created_usernames": [],
                    },
                    ensure_ascii=False,
                )
            )
            return

        password_env = options["password_env"]
        password = os.environ.get(password_env, "")
        if not password:
            raise CommandError(f"Set {password_env} before creating trial accounts.")

        created_usernames: list[str] = []
        email_domain = options["email_domain"].strip() or "research-os.local"
        for username in missing_usernames:
            user = User(
                username=username,
                email=f"{username}@{email_domain}",
                is_active=True,
                is_staff=False,
                is_superuser=False,
            )
            user.set_password(password)
            user.save()
            created_usernames.append(username)

        self.stdout.write(
            json.dumps(
                {
                    "dry_run": False,
                    "planned_count": count,
                    "existing_usernames": sorted(existing_usernames),
                    "missing_usernames": missing_usernames,
                    "created_usernames": created_usernames,
                },
                ensure_ascii=False,
            )
        )
