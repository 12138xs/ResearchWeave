from django.core.management.base import BaseCommand
from apps.materials.models import Material


class Command(BaseCommand):
    help = '按既有旧论文关联回填待分类材料；默认只报告数量，不修改原文或证据。'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        rows = Material.objects.filter(content_type='other', internal_ai_blocked=False,
            versions__legacy_links__paper__isnull=False).values('pk').distinct()
        targets = Material.objects.filter(pk__in=rows, content_type='other', internal_ai_blocked=False)
        count = targets.update(content_type='paper') if options['apply'] else targets.count()
        self.stdout.write(f"{'applied' if options['apply'] else 'dry-run'}: {count}")
