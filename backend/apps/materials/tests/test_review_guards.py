"""LDB-2C-B：Q01–Q16 固定聚焦分母；公开合成数据，无真实队列。"""
import hashlib
import re
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection
from django.db.models.query import QuerySet
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.materials.models import Evidence, Material, MaterialVersion, ResearchCard, StructureChunk, StructureIndex
from apps.materials.services import parse_version, retry_version, review_evidence
from apps.materials.structure import build_structure
from apps.materials.views import EvidenceReview
from apps.tasks.models import TaskRecord


class ReviewGuardTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix='review-guards-')
        self.addCleanup(self.temp.cleanup)
        config = override_settings(STORAGE_ROOT=self.temp.name)
        config.enable()
        self.addCleanup(config.disable)
        self.owner = get_user_model().objects.create_user(username='synthetic-owner')
        self.other = get_user_model().objects.create_user(username='synthetic-other')
        self.staff = get_user_model().objects.create_user(username='synthetic-staff', is_staff=True)

    def version(self, status='needs_review', fmt='md', body=b'Synthetic text', team=False):
        material = Material.objects.create(title='Synthetic', owner=self.owner, visibility='team' if team else 'private')
        key = f'v{material.pk}.md'
        Path(self.temp.name, key).write_bytes(body)
        task = TaskRecord.objects.create(task_type='material_parse', status='failed', progress=100,
                                        result={'old': True}, created_by=self.owner)
        return MaterialVersion.objects.create(material=material, number=1, sha256=hashlib.sha256(body).hexdigest(),
            filename='synthetic.md', storage_key=key, size=len(body), format=fmt, status=status,
            task=task, created_by=self.owner)

    def evidence(self, version, text='Synthetic text', required=True, by=None, at=None):
        return Evidence.objects.create(version=version, ordinal=version.evidence.count() + 1, text=text,
            page=1 if version.format == 'pdf' else None, line_start=1, line_end=1,
            review_required=required, reviewed_by=by, reviewed_at=at)

    def products(self, version, evidence=None):
        index = StructureIndex.objects.create(version=version, parser_version='old', source_sha256='b' * 64, is_current=True)
        StructureChunk.objects.create(index=index, ordinal=1, text='old', line_start=1, line_end=1,
                                      evidence_ids=[evidence.pk] if evidence else [])
        card = ResearchCard.objects.create(version=version, title='old', markdown='old', sha256='c' * 64, created_by=self.owner)
        if evidence:
            card.evidence.add(evidence)

    def all_tables(self):
        with connection.cursor() as cursor:
            snapshot = {}
            for table in sorted(connection.introspection.table_names()):
                cursor.execute('SELECT * FROM ' + connection.ops.quote_name(table))
                snapshot[table] = sorted(map(repr, cursor.fetchall()))
            return snapshot

    def outputs(self, version):
        return [list(q.order_by('pk').values()) for q in (
            version.evidence.all(), version.cards.all(), version.structure_indexes.all(),
            StructureChunk.objects.filter(index__version=version),
            ResearchCard.evidence.through.objects.filter(researchcard__version=version))]

    @contextmanager
    def dml(self):
        writes = []
        def track(execute, sql, params, many, context):
            if re.match(r'\s*(INSERT|UPDATE|DELETE)\b', sql, re.I):
                writes.append(sql)
            return execute(sql, params, many, context)
        with connection.execute_wrapper(track):
            yield writes

    def request(self, version, evidence, user=None, confirmed=True, material_id=None, version_id=None):
        request = APIRequestFactory().post('/', {'confirmed': confirmed}, format='json')
        force_authenticate(request, user=user or self.owner)
        return EvidenceReview.as_view()(request, pk=material_id if material_id is not None else version.material_id,
            version_id=version_id if version_id is not None else version.pk, evidence_id=evidence.pk)

    def rejected(self, version, evidence, status=400, **kwargs):
        before = self.all_tables()
        with self.dml() as writes:
            response = self.request(version, evidence, **kwargs)
        self.assertEqual(response.status_code, status)
        self.assertEqual(writes, [])
        self.assertEqual(self.all_tables(), before)
        return response

    def allowed(self, version, evidence, user=None):
        before = self.all_tables()
        other_evidence = list(Evidence.objects.exclude(pk=evidence.pk).order_by('pk').values())
        other_versions = list(MaterialVersion.objects.exclude(pk=version.pk).order_by('pk').values())
        with self.dml() as writes:
            response = self.request(version, evidence, user=user)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'detail': '已记录核对结果。'})
        for sql in writes:
            self.assertRegex(sql, r'^UPDATE "materials_(evidence|materialversion)" ')
        after = self.all_tables()
        for table in before:
            if table not in {'materials_evidence', 'materials_materialversion'}:
                self.assertEqual(after[table], before[table], table)
        self.assertEqual(list(Evidence.objects.exclude(pk=evidence.pk).order_by('pk').values()), other_evidence)
        self.assertEqual(list(MaterialVersion.objects.exclude(pk=version.pk).order_by('pk').values()), other_versions)
        version.refresh_from_db()
        evidence.refresh_from_db()

    def test_q01_phase_rejection(self):
        for phase in ('queued', 'processing', 'failed', 'unknown'):
            with self.subTest(phase=phase):
                version = self.version(status=phase)
                evidence = self.evidence(version)
                self.products(version, evidence)
                self.rejected(version, evidence)

    def test_q02_target_partial_metadata(self):
        for by, at in ((self.owner, None), (None, timezone.now())):
            for required in (False, True):
                with self.subTest(by=by is not None, at=at is not None, required=required):
                    version = self.version()
                    evidence = self.evidence(version, by=by, at=at, required=required)
                    self.products(version, evidence)
                    self.rejected(version, evidence)

    def test_q03_target_conflicting_flag(self):
        version = self.version()
        evidence = self.evidence(version, by=self.owner, at=timezone.now())
        self.products(version, evidence)
        self.rejected(version, evidence)

    def test_q04_empty_targets_and_siblings(self):
        for text in ('', ' \t\n', '\u00a0'):
            with self.subTest(text=repr(text)):
                version = self.version(fmt='pdf')
                evidence = self.evidence(version, text=text)
                self.rejected(version, evidence)
        # 合法目标保存；异常 sibling 不能使整版升态，也不能被批量修复。
        for fields in ({'text': '', 'required': False}, {'required': False, 'by': self.owner},
                       {'required': True, 'by': self.owner, 'at': timezone.now()}, {'required': False}):
            with self.subTest(sibling=fields):
                version = self.version(fmt='pdf')
                evidence = self.evidence(version)
                self.evidence(version, **fields)
                self.allowed(version, evidence)
                self.assertEqual(version.status, 'needs_review')
                self.assertFalse(evidence.review_required)
                self.assertEqual(evidence.reviewed_by_id, self.owner.pk)
                self.assertIsNotNone(evidence.reviewed_at)

    def test_q05_pdf_partial_then_complete(self):
        version = self.version(fmt='pdf')
        first, second = self.evidence(version), self.evidence(version)
        self.allowed(version, first)
        self.assertEqual(version.status, 'needs_review')
        self.allowed(version, second)
        self.assertEqual(version.status, 'ready')
        for evidence in (first, second):
            self.assertFalse(evidence.review_required)
            self.assertEqual(evidence.reviewed_by_id, self.owner.pk)
            self.assertIsNotNone(evidence.reviewed_at)

    def test_q06_pdf_unmarked_target_gets_real_confirmation(self):
        version = self.version(fmt='pdf')
        evidence = self.evidence(version, required=False)
        start = timezone.now()
        self.allowed(version, evidence)
        self.assertEqual(version.status, 'ready')
        self.assertEqual(evidence.reviewed_by_id, self.owner.pk)
        self.assertGreaterEqual(evidence.reviewed_at, start)

    def test_q07_markdown_no_mass_review_requirement(self):
        for phase in ('needs_review', 'ready'):
            with self.subTest(phase=phase):
                version = self.version(status=phase)
                target = self.evidence(version, required=False)
                sibling = self.evidence(version, required=False)
                self.evidence(version, text='', required=False)
                self.allowed(version, target)
                self.assertEqual(version.status, 'ready')
                sibling.refresh_from_db()
                self.assertIsNone(sibling.reviewed_by_id)
                self.assertIsNone(sibling.reviewed_at)

    def test_q08_ready_repeat_preserves_actor_time(self):
        version = self.version(status='ready', fmt='pdf', team=True)
        stamp = timezone.now()
        evidence = self.evidence(version, required=False, by=self.owner, at=stamp)
        self.products(version, evidence)
        self.allowed(version, evidence, self.staff)
        self.allowed(version, evidence, self.staff)
        self.assertEqual(version.status, 'ready')
        self.assertEqual((evidence.review_required, evidence.reviewed_by_id, evidence.reviewed_at), (False, self.owner.pk, stamp))
        # L1: 成功重复请求不对 Version.updated_at 的旧触碰行为作新限制。

    def test_q09_ready_collection_rejected_before_target_write(self):
        cases = [('pdf', {'text': '', 'required': False, 'by': self.owner, 'at': timezone.now()}),
                 ('pdf', {'required': False}),
                 ('md', {'required': False, 'by': self.owner}),
                 ('md', {'required': False, 'at': timezone.now()}),
                 ('md', {'required': True, 'by': self.owner, 'at': timezone.now()}),
                 ('md', {'required': True})]
        for fmt, fields in cases:
            for confirmed in (False, True):
                with self.subTest(fmt=fmt, fields=fields, confirmed=confirmed):
                    version = self.version(status='ready', fmt=fmt)
                    evidence = self.evidence(version, required=False,
                        by=self.owner if confirmed else None, at=timezone.now() if confirmed else None)
                    self.evidence(version, **fields)
                    self.products(version, evidence)
                    self.rejected(version, evidence)

    def test_q10_confirmation_precedes_queries(self):
        version = self.version()
        evidence = self.evidence(version)
        before = self.all_tables()
        for confirmed in (False, None, 1, 'true'):
            with self.subTest(confirmed=confirmed), self.assertNumQueries(0), self.dml() as writes:
                response = self.request(version, evidence, confirmed=confirmed)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(writes, [])
        self.assertEqual(self.all_tables(), before)

    def test_q11_permissions_and_fixed_version_precede_phase(self):
        version = self.version(status='queued')
        evidence = self.evidence(version)
        for user in (self.other, self.staff):
            with self.subTest(user=user.username):
                self.rejected(version, evidence, status=404, user=user)
        other = self.version(status='queued')
        for args in ({'material_id': other.material_id, 'version_id': other.pk},
                     {'version_id': 999999}, {'material_id': 999999}):
            with self.subTest(args=args):
                self.rejected(version, evidence, status=404, **args)
        empty = self.version()
        self.rejected(empty, evidence, status=404)
        team = self.version(team=True)
        target = self.evidence(team)
        self.allowed(team, target, self.staff)
        self.assertEqual(target.reviewed_by_id, self.staff.pk)

    def test_q12_evidence_and_version_failures_roll_back_every_table(self):
        for point in ('evidence', 'version'):
            with self.subTest(point=point):
                version = self.version()
                evidence = self.evidence(version)
                self.products(version, evidence)
                before = self.all_tables()
                model = Evidence if point == 'evidence' else MaterialVersion
                original = model.save
                def fail_after_save(instance, *args, **kwargs):
                    original(instance, *args, **kwargs)
                    raise DatabaseError('synthetic_review_failure')
                with patch.object(model, 'save', fail_after_save):
                    with self.assertRaisesRegex(DatabaseError, '^synthetic_review_failure$'):
                        review_evidence(self.owner, version.material_id, version.pk, evidence.pk, True)
                self.assertEqual(self.all_tables(), before)

    def test_q13_retry_matrix_and_repeat_preserved(self):
        for phase, stale, expected in [('queued', False, 409), ('processing', False, 409), ('queued', True, 202),
                ('processing', True, 202), ('failed', False, 202), ('ready', True, 200), ('needs_review', True, 200)]:
            with self.subTest(phase=phase, stale=stale):
                version = self.version(status=phase)
                self.products(version, self.evidence(version))
                before = self.outputs(version)
                if stale:
                    MaterialVersion.objects.filter(pk=version.pk).update(updated_at=timezone.now()-timedelta(minutes=6))
                with patch('apps.materials.tasks.parse_material.apply_async') as broker:
                    with self.captureOnCommitCallbacks(execute=True):
                        self.assertEqual(retry_version(self.owner, version.material_id, version.pk)[0], expected)
                    self.assertEqual(broker.call_count, int(expected == 202))
                    if expected == 202:
                        with self.captureOnCommitCallbacks(execute=True):
                            self.assertEqual(retry_version(self.owner, version.material_id, version.pk)[0], 409)
                        self.assertEqual(broker.call_count, 1)
                self.assertEqual(self.outputs(version), before)

    def test_q14_broker_failure_keeps_products(self):
        version = self.version(status='failed')
        self.products(version, self.evidence(version))
        before = self.all_tables()
        with patch('apps.materials.tasks.parse_material.apply_async', side_effect=RuntimeError('synthetic')) as broker:
            for attempt in (1, 2):
                with self.subTest(attempt=attempt), self.captureOnCommitCallbacks(execute=True):
                    self.assertEqual(retry_version(self.owner, version.material_id, version.pk)[0], 202)
                version.refresh_from_db()
                self.assertEqual(version.status, 'failed')
                self.assertEqual(broker.call_count, attempt)
        for table, values in self.all_tables().items():
            if table not in {'materials_materialversion', 'tasks_taskrecord'}:
                self.assertEqual(values, before[table], table)

    def test_q15_parse_safety_boundaries(self):
        for phase in ('ready', 'needs_review'):
            with self.subTest(terminal=phase):
                version = self.version(status=phase)
                self.products(version, self.evidence(version))
                before = self.all_tables()
                with patch('apps.materials.services._extract') as extract:
                    parse_version(version.pk); parse_version(version.pk)
                    extract.assert_not_called()
                self.assertEqual(self.all_tables(), before)
        with self.subTest(case='success-repeat'):
            version = self.version(status='queued')
            parse_version(version.pk)
            version.refresh_from_db()
            self.assertEqual(version.status, 'ready')
            self.assertEqual(version.evidence.count(), 1)
            before = self.all_tables()
            parse_version(version.pk)
            self.assertEqual(self.all_tables(), before)
        for mode in ('extract', 'insert', 'collision', 'bad-file'):
            with self.subTest(failure=mode):
                version = self.version(status='failed', body=b'\xff' if mode == 'bad-file' else b'Synthetic text')
                self.products(version, self.evidence(version) if mode in {'extract', 'collision'} else None)
                before = self.outputs(version)
                original_bytes = Path(self.temp.name, version.storage_key).read_bytes()
                if mode == 'extract':
                    with patch('apps.materials.services._extract', side_effect=ValueError('synthetic')):
                        parse_version(version.pk)
                elif mode == 'insert':
                    original = Evidence.objects.bulk_create
                    def fail_after_insert(rows):
                        original(rows)
                        raise DatabaseError('synthetic')
                    with patch('apps.materials.services.Evidence.objects.bulk_create', side_effect=fail_after_insert):
                        parse_version(version.pk)
                else:
                    parse_version(version.pk)
                version.refresh_from_db()
                self.assertEqual(version.status, 'failed')
                self.assertEqual(self.outputs(version), before)
                self.assertEqual(Path(self.temp.name, version.storage_key).read_bytes(), original_bytes)
        with self.subTest(case='real-blank-pdf'):
            from pypdf import PdfWriter
            version = self.version(status='queued', fmt='pdf')
            path = Path(self.temp.name, version.storage_key)
            writer = PdfWriter(); writer.add_blank_page(width=72, height=72)
            with path.open('wb') as stream:
                writer.write(stream)
            MaterialVersion.objects.filter(pk=version.pk).update(sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            parse_version(version.pk); version.refresh_from_db()
            self.assertEqual(version.status, 'needs_review')
            self.rejected(version, version.evidence.get())

    def test_q16_structure_and_final_task_failure_atomicity(self):
        with self.subTest(point='current-activation'):
            version = self.version(status='ready')
            self.products(version, self.evidence(version))
            before = self.all_tables()
            original = StructureIndex.save
            def fail_activation(index, *args, **kwargs):
                if index.parser_version != 'old' and index.is_current:
                    raise DatabaseError('synthetic')
                return original(index, *args, **kwargs)
            with patch.object(StructureIndex, 'save', fail_activation):
                with self.assertRaises(DatabaseError):
                    build_structure(version.pk)
            self.assertEqual(self.all_tables(), before)
        with self.subTest(point='parse-structure'):
            version = self.version(status='queued')
            self.products(version)
            old = self.outputs(version)
            with patch('apps.materials.structure.StructureChunk.objects.bulk_create', side_effect=DatabaseError('synthetic')):
                parse_version(version.pk)
            version.refresh_from_db(); version.task.refresh_from_db()
            self.assertEqual((version.status, version.task.status), ('ready', 'success'))
            self.assertEqual(version.evidence.count(), 1)
            self.assertTrue(version.warnings)
            self.assertEqual(self.outputs(version)[1:], old[1:])
        with self.subTest(point='final-task'):
            version = self.version(status='queued')
            self.products(version)
            before = self.outputs(version)
            original = QuerySet.update
            def fail_success(queryset, **values):
                if queryset.model is TaskRecord and values.get('status') == 'success':
                    raise DatabaseError('synthetic')
                return original(queryset, **values)
            with patch.object(QuerySet, 'update', fail_success):
                with self.assertRaises(DatabaseError):
                    parse_version(version.pk)
            version.refresh_from_db(); version.task.refresh_from_db()
            self.assertEqual((version.status, version.task.status), ('processing', 'running'))
            self.assertEqual(self.outputs(version), before)
