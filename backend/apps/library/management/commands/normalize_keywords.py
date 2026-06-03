from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.library.keywords import merge_known_keyword_aliases, prune_non_english_keywords


class Command(BaseCommand):
    help = "Merge known duplicate keyword aliases and remove non-English keywords."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Show planned merges without changing data.")

    def handle(self, *args, **options) -> None:
        changes = merge_known_keyword_aliases(dry_run=options["dry_run"])
        pruned = prune_non_english_keywords(dry_run=options["dry_run"])
        if not changes and not pruned:
            self.stdout.write("No keyword normalization changes needed.")
            return
        mode = "Would merge" if options["dry_run"] else "Merged"
        for change in changes:
            self.stdout.write(
                f"{mode} {change['alias']} -> {change['canonical']} "
                f"(papers={len(change['papers'])}, documents={len(change['documents'])})"
            )
        prune_mode = "Would remove" if options["dry_run"] else "Removed"
        for change in pruned:
            self.stdout.write(
                f"{prune_mode} non-English keyword {change['keyword']} "
                f"(papers={len(change['papers'])}, documents={len(change['documents'])})"
            )
