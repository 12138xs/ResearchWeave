"""Operator-run batch registration; originals stay in server-managed storage."""
import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from rest_framework.exceptions import ValidationError

from apps.materials.services import enqueue, ingest, parse_version


class Command(BaseCommand):
    help = "按指定文件批量登记材料；相同可见范围内重复文件不会重复入库。"

    def add_arguments(self, parser):
        parser.add_argument("files", nargs="+")
        parser.add_argument("--owner", required=True, help="登记成员的用户名")
        parser.add_argument("--visibility", choices=["team", "private"], default="team")
        parser.add_argument("--parse", action="store_true", help="在当前进程解析；默认交给队列")

    def handle(self, *args, **options):
        owner = get_user_model().objects.filter(username=options["owner"], is_active=True).first()
        if owner is None:
            raise CommandError("登记成员不存在或已停用。")
        failed = 0
        for filename in options["files"]:
            path = Path(filename)
            try:
                with path.open("rb") as handle:
                    version, created = ingest(File(handle, name=path.name), owner=owner, visibility=options["visibility"])
                if options["parse"]:
                    parse_version(version.pk)
                elif created or version.status == "failed":
                    enqueue(version.pk)
                version.refresh_from_db()
                failed += version.status == "failed"
                self.stdout.write(json.dumps({"filename": path.name, "material_id": version.material_id,
                    "version_id": version.pk, "created": created, "status": version.status}, ensure_ascii=False))
            except (OSError, ValidationError):
                failed += 1
                self.stdout.write(json.dumps({"filename": path.name, "status": "failed", "error": "文件不可读或不满足入库要求。"}, ensure_ascii=False))
        if failed:
            raise CommandError(f"{failed} 个文件未成功处理；其他文件的结果已保留，可修正后重复执行。")
