from django.core.management.base import BaseCommand
from apps.materials.models import MaterialVersion
from apps.materials.structure import build_structure


class Command(BaseCommand):
    help = '构建Markdown结构索引；默认只报告待处理版本，原文件及Evidence保持不变。'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--version', type=int, action='append')

    def handle(self, *args, **options):
        rows = MaterialVersion.objects.filter(format='md', status__in=['ready', 'needs_review']).order_by('pk')
        if options['version']:
            rows = rows.filter(pk__in=options['version'])
        self.stdout.write(f"{'apply' if options['apply'] else 'dry-run'}: {rows.count()}")
        if options['apply']:
            for row in rows.iterator():
                index = build_structure(row.pk)
                self.stdout.write(f'version={row.pk} index={index.pk} chunks={index.chunks.count()}')
