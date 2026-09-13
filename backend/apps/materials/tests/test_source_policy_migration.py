from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class SourcePolicyMigrationTests(TransactionTestCase):
    def test_historical_materials_are_unclassified_and_blocked(self):
        old = [("materials", "0002_evidence_review")]
        new = [("materials", "0003_source_kind_external_access")]
        executor = MigrationExecutor(connection)
        executor.migrate(old)
        try:
            old_apps = executor.loader.project_state(old).apps
            User = old_apps.get_model("auth", "User")
            Material = old_apps.get_model("materials", "Material")
            owner = User.objects.create(username="legacy-material-owner")
            material = Material.objects.create(title="历史 PDF", owner=owner, visibility="team")
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(new)
        apps = executor.loader.project_state(new).apps
        Material = apps.get_model("materials", "Material")
        migrated = Material.objects.get(pk=material.pk)
        self.assertEqual(migrated.source_kind, "unclassified")
        self.assertEqual(migrated.external_agent_access, "blocked")
        self.assertIsNone(migrated.external_access_changed_by_id)
        self.assertIsNone(migrated.external_access_changed_at)
