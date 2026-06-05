from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase, override_settings

from config import settings as project_settings
from config.release import load_release_info, sanitize_source_repo


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

    def test_current_release_metadata_extends_static_release_info(self) -> None:
        with TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "backend"
            base_dir.mkdir()
            (Path(tmpdir) / "release.json").write_text(
                """{
  "product": "A510知识库",
  "version": "v1.2.3",
  "released_at": "2026-06-03",
  "summary": "static release",
  "migration_state": "ok"
}
""",
                encoding="utf-8",
            )
            (Path(tmpdir) / "current-release.json").write_text(
                """{
  "deployed_at": "2026-06-03T00:00:00+00:00",
  "git_commit": "abc123",
  "source_repo": "https://github.com/example/research-weave",
  "source_ref": "main",
  "artifact_hash": "sha256:test",
  "dirty": false
}
""",
                encoding="utf-8",
            )

            with override_settings(BASE_DIR=base_dir):
                load_release_info.cache_clear()
                release = load_release_info()

        self.assertEqual(release["version"], "v1.2.3")
        self.assertEqual(release["git_commit"], "abc123")
        self.assertEqual(release["source_ref"], "main")
        self.assertEqual(release["dirty"], "False")

    def test_source_repo_metadata_strips_credentials_query_and_fragment(self) -> None:
        self.assertEqual(
            sanitize_source_repo("https://token@example.com/org/repo.git?secret=1#frag"),
            "https://example.com/org/repo.git",
        )
        self.assertEqual(
            sanitize_source_repo("https://user:pass@example.com/org/repo.git"),
            "https://example.com/org/repo.git",
        )

    def test_loaded_current_release_sanitizes_source_repo_credentials(self) -> None:
        with TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "backend"
            base_dir.mkdir()
            (Path(tmpdir) / "current-release.json").write_text(
                """{
  "source_repo": "https://token@example.com/org/repo.git?secret=1#frag"
}
""",
                encoding="utf-8",
            )

            with override_settings(BASE_DIR=base_dir):
                load_release_info.cache_clear()
                release = load_release_info()

        self.assertEqual(release["source_repo"], "https://example.com/org/repo.git")
        self.assertNotIn("token", release["source_repo"])
        self.assertNotIn("secret", release["source_repo"])
