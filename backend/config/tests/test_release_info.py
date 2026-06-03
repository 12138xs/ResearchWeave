from __future__ import annotations

from django.test import SimpleTestCase, override_settings

from config.release import load_release_info
from config import settings as project_settings


class ReleaseInfoTests(SimpleTestCase):
    def setUp(self) -> None:
        load_release_info.cache_clear()

    def tearDown(self) -> None:
        load_release_info.cache_clear()

    def test_release_info_loads_from_project_release_file(self) -> None:
        release = load_release_info()

        self.assertEqual(release["product"], "A510知识库")
        self.assertRegex(release["version"], r"^v\d+\.\d+\.\d+$")
        self.assertIn("released_at", release)
        self.assertIn("summary", release)
        self.assertIn("migration_state", release)

    @override_settings(APP_VERSION="v9.9.9-test")
    def test_environment_can_override_version_for_deployment_metadata(self) -> None:
        release = load_release_info()

        self.assertEqual(release["version"], "v9.9.9-test")

    @override_settings(BASE_DIR=project_settings.BASE_DIR)
    def test_backend_build_context_contains_release_file(self) -> None:
        self.assertTrue((project_settings.BASE_DIR / "release.json").exists())
