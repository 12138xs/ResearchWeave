"""输出单个有界、脱敏、零写入的登记计划。"""
from django.core.management.base import BaseCommand, CommandError

from apps.registry import batch, services


class Command(BaseCommand):
    help = '按单一类型和冻结范围生成只读登记计划；不执行登记。'
    requires_system_checks = []

    def create_parser(self, prog_name, subcommand, **kwargs):
        parser = super().create_parser(prog_name, subcommand, **kwargs)

        def safe_error(message):
            # argparse 默认会回显非法参数原文，这里只保留稳定原因码。
            if self._called_from_command_line:
                parser.exit(2, 'CommandError: invalid_arguments\n')
            raise CommandError('invalid_arguments', returncode=2)

        parser.error = safe_error
        return parser

    def add_arguments(self, parser):
        parser.add_argument('--kind', required=True)
        parser.add_argument('--actor-id', required=True)
        parser.add_argument('--after-pk', default=0)
        parser.add_argument('--through-pk')
        parser.add_argument('--limit', default=20)
        parser.add_argument('--cutoff', help='含时区的 ISO8601 时间；缺省冻结为启动时 UTC。')

    def handle(self, *args, **options):
        try:
            manifest = batch.plan_batch(**{key: options[key] for key in (
                'kind', 'actor_id', 'after_pk', 'through_pk', 'limit', 'cutoff')})
            output = services.canonical(manifest)
        except batch.PlanError as error:
            raise CommandError(error.code, returncode=2) from None
        except Exception:
            raise CommandError('unexpected_error', returncode=2) from None
        self.stdout.write(output)
