from __future__ import annotations

from types import SimpleNamespace

from django.test import SimpleTestCase
from rest_framework.permissions import IsAuthenticated

from apps.experiments.views import (
    ExperimentDetailView,
    ExperimentListView,
    ExperimentRunDetailView,
    ExperimentRunExecuteView,
    ExperimentRunListView,
)


class ExperimentPermissionTests(SimpleTestCase):
    def assert_permission(self, view_cls, method: str, expected_type: type) -> None:
        view = view_cls()
        view.request = SimpleNamespace(method=method)
        permissions = view.get_permissions()
        self.assertEqual(len(permissions), 1)
        self.assertIsInstance(permissions[0], expected_type)

    def test_reads_require_login(self) -> None:
        for view_cls in [ExperimentListView, ExperimentDetailView, ExperimentRunListView, ExperimentRunDetailView]:
            with self.subTest(view=view_cls.__name__):
                self.assert_permission(view_cls, "GET", IsAuthenticated)

    def test_writes_require_login(self) -> None:
        for view_cls, method in [
            (ExperimentListView, "POST"),
            (ExperimentDetailView, "PATCH"),
            (ExperimentRunListView, "POST"),
            (ExperimentRunDetailView, "PATCH"),
            (ExperimentRunExecuteView, "POST"),
        ]:
            with self.subTest(view=view_cls.__name__, method=method):
                self.assert_permission(view_cls, method, IsAuthenticated)
