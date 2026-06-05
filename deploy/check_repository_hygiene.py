from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


REQUIRED_TRACKED_FILES = {".env.example", "README.md", ".github/workflows/ci.yml"}
GITHUB_LOCAL_ONLY_FILES = {"AGENTS.md"}
GITHUB_LOCAL_ONLY_DIRS = {"docs", "scripts", "tools"}
IGNORED_PATH_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tmp-chrome-ui-check",
}
IGNORED_ROOT_DIRS = {"secrets", "storage", "backups", "logs", "release-backups", "config-backups"}
FORBIDDEN_FILE_NAMES = {".env", "current-release.json"}
FORBIDDEN_SUFFIXES = {
    ".sql",
    ".dump",
    ".db",
    ".sqlite",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".tgz",
    ".tar.gz",
}
TEXT_SUFFIXES = {".md", ".txt", ".py", ".ts", ".tsx", ".css", ".json", ".yml", ".yaml", ".sh"}
PUBLIC_TEXT_ENTRYPOINTS = {"README.md", ".env.example"}
WINDOWS_LAB_PATH_PATTERN = r"D:" + r"\\\\labs\\\\[^\\\s]+|D:" + r"/labs/[^/\s]+"
SENSITIVE_TEXT_PATTERNS = [
    re.compile(r"\b172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}\b(?!/\d{1,2})"),
    re.compile(WINDOWS_LAB_PATH_PATTERN),
    re.compile(r"/home/data\d+/[A-Za-z0-9_.-]+"),
    re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
]
MOJIBAKE_SENTINELS = [
    "锟",
    "閺",
    "鐭",
    "鏂",
    "鍥",
    "绱",
    "璁",
    "鈥",
    "€",
]


def discover_root() -> Path:
    return Path(__file__).resolve().parents[1]


def tracked_files_for(root: Path) -> set[str]:
    try:
        output = subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return filesystem_files_for(root)
    files = {line.strip().replace("\\", "/") for line in output.splitlines() if line.strip()}
    return files or filesystem_files_for(root)


def filesystem_files_for(root: Path) -> set[str]:
    files: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file() or is_ignored_for_scan(path, root):
            continue
        files.add(path.relative_to(root).as_posix())
    return files


def is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name == ".env.example"


def is_ignored_for_scan(path: Path, root: Path) -> bool:
    rel_parts = path.relative_to(root).parts
    if set(rel_parts) & IGNORED_PATH_PARTS:
        return True
    return bool(rel_parts and rel_parts[0] in IGNORED_ROOT_DIRS)


def is_github_local_only_path(rel: str) -> bool:
    if rel in GITHUB_LOCAL_ONLY_FILES:
        return True
    return any(rel == directory or rel.startswith(f"{directory}/") for directory in GITHUB_LOCAL_ONLY_DIRS)


def collect_failures(root: Path, tracked_files: set[str] | None = None) -> list[str]:
    root = root.resolve()
    tracked_files = tracked_files_for(root) if tracked_files is None else tracked_files
    failures: list[str] = []

    for required in sorted(REQUIRED_TRACKED_FILES):
        if required not in tracked_files:
            failures.append(f"required tracked file missing: {required}")

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()

        if rel in GITHUB_LOCAL_ONLY_FILES or is_github_local_only_path(rel):
            failures.append(f"github-local-only path: {rel}")
            continue
        if path.name in FORBIDDEN_FILE_NAMES:
            failures.append(f"forbidden file: {rel}")
            continue
        if path.name.startswith(".env.") and path.name != ".env.example":
            failures.append(f"forbidden env backup: {rel}")
            continue
        if is_ignored_for_scan(path, root):
            continue
        if any(path.name.lower().endswith(suffix) for suffix in FORBIDDEN_SUFFIXES):
            failures.append(f"forbidden artifact suffix: {rel}")
            continue
        if not is_text_file(path):
            continue

        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in SENSITIVE_TEXT_PATTERNS:
            if pattern.search(text):
                failures.append(f"sensitive text match {pattern.pattern!r}: {rel}")
                break
        if "\ufffd" in text:
            failures.append(f"encoding replacement character: {rel}")
        if rel in PUBLIC_TEXT_ENTRYPOINTS and any(sentinel in text for sentinel in MOJIBAKE_SENTINELS):
            failures.append(f"mojibake sentinel: {rel}")

    return failures


def main() -> int:
    failures = collect_failures(discover_root())
    if failures:
        print("Repository hygiene check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Repository hygiene check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
