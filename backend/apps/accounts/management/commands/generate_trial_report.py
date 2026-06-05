from __future__ import annotations

from collections import Counter
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.papers.models import Paper
from apps.tasks.models import TaskRecord


class Command(BaseCommand):
    help = "Write a Markdown readiness report for the Research OS team trial."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--output", required=True, help="Report path to write.")
        parser.add_argument("--backup-dir", default="", help="Backup directory verified during readiness.")
        parser.add_argument("--restore-status", default="not-run", help="Backup restore check status.")
        parser.add_argument("--smoke-status", default="not-run", help="Trial smoke check status.")
        parser.add_argument("--resource-snapshot", default="", help="Short resource observation summary.")
        parser.add_argument("--trial-prefix", default="trial", help="Trial username prefix.")
        parser.add_argument(
            "--member-usernames",
            default="",
            help="Comma or whitespace separated member usernames expected during team trial.",
        )

    def handle(self, *args, **options) -> None:
        trial_prefix = options["trial_prefix"].strip()
        User = get_user_model()
        trial_account_count = User.objects.filter(username__startswith=trial_prefix, is_active=True).count()
        member_usernames = _parse_usernames(options["member_usernames"])
        existing_member_usernames = set(
            User.objects.filter(username__in=member_usernames, is_active=True).values_list("username", flat=True)
        )
        missing_member_usernames = [
            username for username in member_usernames if username not in existing_member_usernames
        ]
        paper_statuses = Counter(Paper.objects.values_list("status", flat=True))
        task_statuses = Counter(TaskRecord.objects.values_list("status", flat=True))
        recent_failures = list(
            TaskRecord.objects.filter(status=TaskRecord.Status.FAILED)
            .order_by("-updated_at", "-id")
            .values_list("id", "task_type", "stage")[:10]
        )

        lines = [
            "# Research OS Trial Readiness Report",
            "",
            f"generated_at: {timezone.now().isoformat()}",
            f"trial accounts: {trial_account_count}",
            f"member accounts: {len(existing_member_usernames)}/{len(member_usernames)}",
            f"missing member accounts: {', '.join(missing_member_usernames) if missing_member_usernames else 'none'}",
            f"backup dir: {options['backup_dir'] or 'not recorded'}",
            f"restore status: {options['restore_status']}",
            f"trial smoke status: {options['smoke_status']}",
            f"resource snapshot: {options['resource_snapshot'] or 'not recorded'}",
            "",
            "## Paper Status",
            "",
            *_counter_lines(paper_statuses),
            "",
            "## Task Status",
            "",
            *_counter_lines(task_statuses),
            "",
            "## Recent Failed Tasks",
            "",
            *_failure_lines(recent_failures),
            "",
            "## 团队试运行签收表",
            "",
            "- [ ] 使用团队成员账号登录",
            "- [ ] 浏览论文库并打开一篇论文详情页",
            "- [ ] 上传一篇非敏感 PDF",
            "- [ ] 运行轻处理，并确认任务页能看到进度",
            "- [ ] 触发深度处理，并确认深度档案已生成",
            "- [ ] 完成当前论文问答",
            "- [ ] 显式选择论文后完成跨论文问答",
            "- [ ] 创建或编辑一篇 Markdown 文档",
            "- [ ] 在文档编辑器中粘贴图片，并确认图片链接可用",
            "- [ ] 打开任务页，检查最近失败任务",
            "- [ ] 核对备份恢复证据",
            "- [ ] 记录已接受的问题或仍需处理的阻塞项",
            "",
            "签收人：____________________",
            "签收日期：____________________",
            "试运行结论：通过 / 带已接受问题通过 / 继续试运行",
            "",
            "## 已退役旧系统边界",
            "",
            "旧 LAB Wiki / Wiki.js / Dify / old portal 栈已退役，不属于当前试运行入口。",
            "除非用户明确提供外部备份并要求回滚，不要重建旧目录或重启旧服务。",
            "",
        ]
        content = "\n".join(lines)
        if options["output"] == "-":
            self.stdout.write(content)
            return

        output = Path(options["output"]).expanduser()
        if output.exists() and output.is_dir():
            raise CommandError("--output must be a file path, not a directory.")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        self.stdout.write(f"trial_report={output}")


def _counter_lines(counter: Counter) -> list[str]:
    if not counter:
        return ["- none: 0"]
    return [f"- {key}: {counter[key]}" for key in sorted(counter)]


def _failure_lines(failures: list[tuple[int, str, str]]) -> list[str]:
    if not failures:
        return ["- none"]
    return [f"- T{task_id:04d} {task_type} stage={stage or 'unknown'}" for task_id, task_type, stage in failures]


def _parse_usernames(raw: str) -> list[str]:
    seen: set[str] = set()
    usernames: list[str] = []
    for item in raw.replace(",", " ").split():
        username = item.strip()
        if not username or username in seen:
            continue
        seen.add(username)
        usernames.append(username)
    return usernames
