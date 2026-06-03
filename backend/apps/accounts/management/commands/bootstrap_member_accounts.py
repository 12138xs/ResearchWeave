from __future__ import annotations

import csv
import json
import os
import secrets
import stat
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create or initialize named Research OS member accounts."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--usernames", required=True, help="Comma or whitespace separated usernames.")
        parser.add_argument(
            "--credentials-output",
            default="",
            help="CSV path for generated initial credentials. Required unless --dry-run is used.",
        )
        parser.add_argument("--email-domain", default="research-os.local", help="Email domain for member users.")
        parser.add_argument("--reset-existing", action="store_true", help="Reset passwords for existing users too.")
        parser.add_argument("--dry-run", action="store_true", help="Report planned accounts without writing users.")

    def handle(self, *args, **options) -> None:
        usernames = _parse_usernames(options["usernames"])
        if not usernames:
            raise CommandError("--usernames must include at least one username.")
        if len(usernames) > 200:
            raise CommandError("--usernames supports at most 200 users per run.")

        User = get_user_model()
        existing_usernames = set(User.objects.filter(username__in=usernames).values_list("username", flat=True))
        missing_usernames = [username for username in usernames if username not in existing_usernames]
        reset_existing = bool(options["reset_existing"])

        if options["dry_run"]:
            self.stdout.write(
                json.dumps(
                    {
                        "dry_run": True,
                        "planned_count": len(usernames),
                        "existing_usernames": [username for username in usernames if username in existing_usernames],
                        "missing_usernames": missing_usernames,
                        "created_usernames": [],
                        "updated_usernames": [],
                        "credentials_output": "",
                    },
                    ensure_ascii=False,
                )
            )
            return

        credentials_output = str(options["credentials_output"]).strip()
        if not credentials_output:
            raise CommandError("--credentials-output is required unless --dry-run is used.")

        email_domain = str(options["email_domain"]).strip() or "research-os.local"
        created_usernames: list[str] = []
        updated_usernames: list[str] = []
        credential_rows: list[dict[str, str]] = []

        for username in usernames:
            password = secrets.token_urlsafe(24)
            user = User.objects.filter(username=username).first()
            if user is None:
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
                credential_rows.append({"username": username, "password": password})
                continue

            user.is_active = True
            user.is_staff = False
            user.is_superuser = False
            if not user.email:
                user.email = f"{username}@{email_domain}"
            if reset_existing:
                user.set_password(password)
                updated_usernames.append(username)
                credential_rows.append({"username": username, "password": password})
            user.save()

        output_path = _write_credentials(credentials_output, credential_rows)
        self.stdout.write(
            json.dumps(
                {
                    "dry_run": False,
                    "planned_count": len(usernames),
                    "existing_usernames": [username for username in usernames if username in existing_usernames],
                    "missing_usernames": missing_usernames,
                    "created_usernames": created_usernames,
                    "updated_usernames": updated_usernames,
                    "credentials_output": str(output_path),
                },
                ensure_ascii=False,
            )
        )


def _parse_usernames(raw: str) -> list[str]:
    seen: set[str] = set()
    usernames: list[str] = []
    for item in raw.replace(",", " ").split():
        username = item.strip()
        if not username:
            continue
        if not username.replace("_", "").replace("-", "").isalnum():
            raise CommandError(f"Invalid username: {username}")
        if username in seen:
            continue
        seen.add(username)
        usernames.append(username)
    return usernames


def _write_credentials(path: str, rows: list[dict[str, str]]) -> Path:
    output = Path(path).expanduser()
    if output.exists() and output.is_dir():
        raise CommandError("--credentials-output must be a file path, not a directory.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["username", "password"])
        writer.writeheader()
        writer.writerows(rows)
    if os.name == "posix":
        output.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return output
