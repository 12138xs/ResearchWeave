"""Explicit, local-only legacy registration. No model or queue calls."""
import hashlib
import json
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.materials.models import LegacyPaperLink, MaterialVersion
from apps.materials.services import MAX_BYTES, ingest, parse_version
from apps.papers.models import Paper
from apps.papers.services.pdf import resolve_paper_pdf_path


class Command(BaseCommand):
    help = "核查旧论文全文；默认只报告，--apply 登记并同步解析，保留旧入口。"

    def add_arguments(self, parser):
        parser.add_argument('--owner', required=True)
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--paper-id', type=int, action='append')
        parser.add_argument('--limit', type=int, default=100)
        parser.add_argument('--after-id', type=int, default=0, help='只处理此编号之后的论文，用于续批')

    def handle(self, *args, **options):
        owner = get_user_model().objects.filter(username=options['owner'], is_active=True, is_staff=True).first()
        if owner is None:
            raise CommandError('请指定有效的管理员作为团队全文登记人。')
        if not 1 <= options['limit'] <= 1000:
            raise CommandError('每批限制必须为 1–1000。')
        papers = Paper.objects.filter(pk__gt=options['after_id']).order_by('pk')
        seen = {}
        if options['paper_id']:
            papers = papers.filter(pk__in=options['paper_id'])
        for paper in papers[:options['limit']]:
            try:
                result = self.process(paper, owner, options['apply'])
            except (OSError, ValueError, ValidationError):
                result = {'status': 'invalid_file'}
            digest = result.get('sha256')
            if not options['apply'] and digest in seen and result['status'] == 'available':
                result.update(status='duplicate', duplicate_of_paper_id=seen[digest])
            if digest:
                seen.setdefault(digest, paper.pk)
            self.stdout.write(json.dumps({'paper_id': paper.pk, **result}, ensure_ascii=False))

    def process(self, paper, owner, apply):
        if not paper.source_pdf_path:
            return {'status': 'abstract_only'}
        path = resolve_paper_pdf_path(paper)
        if path is None:
            return {'status': 'missing_file'}
        if not 0 < path.stat().st_size <= MAX_BYTES:
            return {'status': 'invalid_file'}
        with path.open('rb') as handle:
            data = handle.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            return {"status": "invalid_file"}
        digest = hashlib.sha256(data).hexdigest()
        link = paper.material_links.filter(original_sha256=digest).select_related('version').first()
        duplicate = MaterialVersion.objects.filter(sha256=digest, material__visibility='team').order_by('pk').first()
        if duplicate and duplicate.material.source_kind != 'paper_fulltext':
            return {'status': 'source_conflict', 'detail': '同内容已有不同或未分类来源，请人工核对；未自动改写。'}
        if not apply:
            return {'status': ('parse_failed' if link.version.status == 'failed' else 'linked') if link else ('duplicate' if duplicate else 'available'),
                    'sha256': digest}
        with transaction.atomic():
            # Serializes reruns for a paper; ingest also serializes duplicate hashes.
            paper = Paper.objects.select_for_update().get(pk=paper.pk)
            link = paper.material_links.filter(original_sha256=digest).select_related('version').first()
            if link:
                version = link.version
            else:
                previous = paper.material_links.select_related('version__material').order_by('-pk').first()
                material = None
                if not duplicate and previous and not LegacyPaperLink.objects.filter(version__material=previous.version.material).exclude(paper=paper).exists():
                    material = previous.version.material
                # A duplicate shared by different papers must not advance their current version together.
                version, _ = ingest(File(BytesIO(data), name='original.pdf'), owner=owner, title=paper.title,
                                    material=material, source_kind='paper_fulltext')
                if version.sha256 != digest or version.material.source_kind != 'paper_fulltext':
                    raise ValidationError('文件或来源在登记期间发生变化。')
                LegacyPaperLink.objects.create(paper=paper, version=version, original_sha256=digest)
        parse_version(version.pk)
        version.refresh_from_db()
        return {'status': 'parse_failed' if version.status == 'failed' else 'linked',
                'material_id': version.material_id, 'version_id': version.pk,
                'sha256': version.sha256, 'parse_status': version.status}
