from __future__ import annotations

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase


MODULE_PATH = Path(__file__).resolve().parents[3] / "deploy" / "check_repository_hygiene.py"
spec = importlib.util.spec_from_file_location("check_repository_hygiene", MODULE_PATH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
collect_failures = module.collect_failures


class RepositoryHygieneTests(TestCase):
    def collect_for_files(
        self,
        files: dict[str, str],
        tracked_files: set[str] | None = None,
        fill_required_files: bool = True,
    ) -> list[str]:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for rel, text in files.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")

            tracked = tracked_files or set(files)
            if fill_required_files:
                tracked.update({".env.example", "README.md", ".github/workflows/ci.yml"})
                for required in tracked:
                    path = root / required
                    if not path.exists() and not any(required == rel for rel in files):
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text("placeholder\n", encoding="utf-8")

            return collect_failures(root, tracked_files=tracked)

    def test_requires_tracked_env_example_template(self) -> None:
        failures = self.collect_for_files(
            {"README.md": "# ResearchWeave\n"},
            tracked_files={"README.md", ".github/workflows/ci.yml"},
            fill_required_files=False,
        )

        self.assertIn("required tracked file missing: .env.example", failures)

    def test_rejects_github_local_only_paths(self) -> None:
        for rel in ["AGENTS.md", "docs/runbook.md", "scripts/export.py", "tools/import.py"]:
            failures = self.collect_for_files({rel: "private\n"})
            self.assertTrue(any("github-local-only path" in failure for failure in failures), rel)

    def test_rejects_env_and_runtime_artifacts(self) -> None:
        samples = {
            ".env": "SECRET_KEY=secret\n",
            ".env.production": "SECRET_KEY=secret\n",
            "current-release.json": "{}\n",
            "dump.sql": "select 1;\n",
            "server.key": "secret\n",
            "archive.tgz": "secret\n",
        }

        for rel, text in samples.items():
            failures = self.collect_for_files({rel: text})
            self.assertTrue(failures, rel)

    def test_rejects_sensitive_text_in_public_files(self) -> None:
        sensitive_private_ip = ".".join(["172", "20", "1", "2"])
        failures = self.collect_for_files({"README.md": f"server {sensitive_private_ip}\n"})

        self.assertTrue(any("sensitive text match" in failure for failure in failures))

    def test_rejects_mojibake_sentinel_text(self) -> None:
        # This mojibake sample is a regression sentinel, not user-facing text.
        failures = self.collect_for_files({"README.md": "ResearchWeave 鍥㈤槦鐭ヨ瘑搴撶\n"})

        self.assertTrue(any("mojibake sentinel" in failure for failure in failures))
