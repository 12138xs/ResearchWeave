"""按显式 UUID 清单输出脱敏只读不变量审计。"""
from django.core.management.base import BaseCommand, CommandError

from apps.registry import batch, services


class Command(BaseCommand):
    help = '只读检查 1–50 个显式 ResearchObject UUID；不扫描或修复。'
    requires_system_checks = []

    def create_parser(self, prog_name, subcommand, **kwargs):
        parser = super().create_parser(prog_name, subcommand, **kwargs)

        def safe_error(message):
            if self._called_from_command_line:
                parser.exit(2, 'CommandError: invalid_arguments\n')
            raise CommandError('invalid_arguments', returncode=2)

        parser.error = safe_error
        return parser

    def add_arguments(self, parser):
        # 空清单由批处理层拒绝，兼容 call_command 的列表关键字参数。
        parser.add_argument('--object-id', action='append')

    def handle(self, *args, **options):
        try:
            manifest = batch.audit_objects(options['object_id'])
            output = services.canonical(manifest)
        except batch.AuditError as error:
            raise CommandError(error.code, returncode=2) from None
        except Exception:
            raise CommandError('unexpected_error', returncode=2) from None
        self.stdout.write(output)
        if manifest['summary']['with_findings'] or manifest['summary']['unavailable']:
            raise CommandError('audit_findings', returncode=3)
