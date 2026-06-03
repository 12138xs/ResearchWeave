from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.search.services import rebuild_search_index


class Command(BaseCommand):
    help = "Rebuild the unified search index from paper, document, and experiment projections."

    def handle(self, *args, **options):
        result = rebuild_search_index()
        self.stdout.write(self.style.SUCCESS(f"indexed={result.get('indexed', 0)}"))
