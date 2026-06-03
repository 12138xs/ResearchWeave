from __future__ import annotations

from pathlib import Path
from io import StringIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.papers.models import Paper
from apps.tasks.models import TaskRecord


class TrialReportCommandTests(TestCase):
    def test_writes_trial_report_without_secrets(self) -> None:
        User = get_user_model()
        User.objects.create_user(username="trial01", password="secret")
        User.objects.create_user(username="trial02", password="secret")
        Paper.objects.create(title="Ready paper", status=Paper.Status.DEEP_READY)
        Paper.objects.create(title="Review paper", status=Paper.Status.NEEDS_REVIEW)
        TaskRecord.objects.create(task_type="deep_process_paper", status=TaskRecord.Status.SUCCESS)
        TaskRecord.objects.create(task_type="paper_light_process", status=TaskRecord.Status.FAILED)

        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "trial-report.md"
            call_command(
                "generate_trial_report",
                "--output",
                str(output_path),
                "--backup-dir",
                "backup-evidence-redacted",
                "--restore-status",
                "ok",
                "--smoke-status",
                "ok",
                "--resource-snapshot",
                "cpu=low;memory=stable",
            )

            content = output_path.read_text(encoding="utf-8")

        self.assertIn("# Research OS Trial Readiness Report", content)
        self.assertIn("trial accounts: 2", content)
        self.assertIn("deep_ready: 1", content)
        self.assertIn("needs_review: 1", content)
        self.assertIn("success: 1", content)
        self.assertIn("failed: 1", content)
        self.assertIn("backup-evidence-redacted", content)
        self.assertIn("restore status: ok", content)
        self.assertIn("trial smoke status: ok", content)
        self.assertIn("cpu=low;memory=stable", content)
        self.assertIn("## 团队试运行签收表", content)
        self.assertIn("- [ ] 使用团队成员账号登录", content)
        self.assertIn("- [ ] 上传一篇非敏感 PDF", content)
        self.assertIn("- [ ] 完成当前论文问答", content)
        self.assertIn("- [ ] 核对备份恢复证据", content)
        self.assertIn("Do not stop or delete old LAB Wiki services without explicit user approval.", content)
        self.assertNotIn("secret", content)

    def test_can_write_trial_report_to_stdout(self) -> None:
        out = StringIO()

        call_command("generate_trial_report", "--output", "-", stdout=out)

        content = out.getvalue()
        self.assertIn("# Research OS Trial Readiness Report", content)
        self.assertIn("Do not stop or delete old LAB Wiki services without explicit user approval.", content)

    def test_reports_member_account_readiness_when_usernames_are_provided(self) -> None:
        User = get_user_model()
        User.objects.create_user(username="member_alpha", password="secret")
        User.objects.create_user(username="member_beta", password="secret")
        out = StringIO()

        call_command(
            "generate_trial_report",
            "--output",
            "-",
            "--member-usernames",
            "member_alpha,member_beta,member_gamma",
            stdout=out,
        )

        content = out.getvalue()
        self.assertIn("member accounts: 2/3", content)
        self.assertIn("missing member accounts: member_gamma", content)
        self.assertNotIn("secret", content)
