from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.storage.provider import get_storage_provider


class Command(BaseCommand):
    help = "Create Research OS runtime storage directories."

    def handle(self, *args, **options):
        provider = get_storage_provider()
        for path in provider.ensure_runtime_dirs():
            self.stdout.write(f"created {path}")
