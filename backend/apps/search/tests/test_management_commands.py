from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase


class SearchManagementCommandTests(SimpleTestCase):
    @patch("apps.search.management.commands.reindex_search.rebuild_search_index")
    def test_reindex_search_command_reports_index_count(self, rebuild_search_index) -> None:
        rebuild_search_index.return_value = {"indexed": 12}
        output = StringIO()

        call_command("reindex_search", stdout=output)

        self.assertIn("indexed=12", output.getvalue())
        rebuild_search_index.assert_called_once_with()
