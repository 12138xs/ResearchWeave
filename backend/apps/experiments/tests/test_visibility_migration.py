from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class VisibilityMigrationTests(TransactionTestCase):
    def test_preserves_existing_shared_projects_and_defaults_new_projects_to_private(self):
        old = [("experiments", "0001_initial")]
        new = [("experiments", "0002_project_visibility")]
        executor = MigrationExecutor(connection)
        executor.migrate(old)
        try:
            old_apps = executor.loader.project_state(old).apps
            old_project = old_apps.get_model("experiments", "ExperimentProject").objects.create(
                title="历史团队实验", slug="legacy-project")
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(new)
        apps = executor.loader.project_state(new).apps
        Project = apps.get_model("experiments", "ExperimentProject")
        self.assertEqual(Project.objects.get(pk=old_project.pk).visibility, "team")
        self.assertEqual(Project.objects.create(title="新实验", slug="new-project").visibility, "private")
