from __future__ import annotations

from django.test import SimpleTestCase

from apps.tasks.serializers import TASK_LABELS


class TaskLabelTests(SimpleTestCase):
    def test_new_async_task_labels_are_human_readable(self) -> None:
        for task_type in [
            "experiment_run_execute",
            "search_reindex",
            "quality_audit",
            "direction_map_generate",
        ]:
            with self.subTest(task_type=task_type):
                self.assertIn(task_type, TASK_LABELS)
                self.assertNotIn("_", TASK_LABELS[task_type])
