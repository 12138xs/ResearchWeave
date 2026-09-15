from django.core.management.base import BaseCommand
from apps.documents.models import DocumentVersion
from apps.documents.structure import build_structure


class Command(BaseCommand):
    help = '检查或重建知识文档结构索引，默认只报告数量'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--document-version', type=int, action='append')

    def handle(self, *args, **options):
        rows = DocumentVersion.objects.all().order_by('pk')
        if options['document_version']:
            rows = rows.filter(pk__in=options['document_version'])
        self.stdout.write(f'文档版本：{rows.count()}；模式：' + ('构建' if options['apply'] else '只读检查'))
        if options['apply']:
            for pk in rows.values_list('pk', flat=True).iterator():
                index = build_structure(pk)
                self.stdout.write(f'version={pk} index={index.pk} chunks={index.chunks.count()}')
