"""LDB-2B：仅合成资产；OBS-15 的 PostgreSQL 并发验收另行执行。"""
import io
import hashlib
import json
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from itertools import product
from pathlib import Path
from datetime import datetime, timezone as datetime_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import DatabaseError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.materials import selectors
from apps.materials.models import Evidence, Material, MaterialVersion, StructureIndex
from apps.materials.quality_observation import ObservationError, observe_version_quality


ISSUES = {
    'unknown_processing_state': ('blocker', 'processing'),
    'parse_failed': ('blocker', 'processing'),
    'no_evidence': ('blocker', 'evidence'),
    'no_text': ('blocker', 'evidence'),
    'page_text_missing': ('warning', 'evidence'),
    'evidence_review_required': ('warning', 'evidence'),
    'review_metadata_incomplete': ('warning', 'evidence'),
    'legacy_status_needs_review': ('warning', 'legacy'),
    'structure_missing': ('info', 'structure'),
    'legacy_warning_present': ('info', 'legacy'),
}
SENTINEL = 'SYNTHETIC_SECRET_body_title_owner_path_token_sql'


class QualityObservationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user(username='quality-owner')
        cls.other = get_user_model().objects.create_user(username='quality-other', is_staff=True)

    def make_version(self, fmt='md', status='ready', visibility='private', structure=True):
        material = Material.objects.create(owner=self.owner, title=SENTINEL, visibility=visibility)
        version = MaterialVersion.objects.create(
            material=material, number=1, sha256='a' * 64, filename=SENTINEL,
            format=fmt, storage_key=SENTINEL, size=1, status=status,
            error=SENTINEL, created_by=self.owner,
        )
        if structure:
            StructureIndex.objects.create(version=version, parser_version='synthetic-v1',
                                          source_sha256='a' * 64, is_current=True)
        return version

    def evidence(self, version, text='Synthetic text', flag=False, by=False, at=False):
        return Evidence.objects.create(
            version=version, ordinal=version.evidence.count() + 1, text=text,
            review_required=flag, reviewed_by=self.owner if by else None,
            reviewed_at=datetime(2026, 1, 1, tzinfo=datetime_timezone.utc) if at else None,
        )

    def observe(self, version, user=None):
        return observe_version_quality(user or self.owner, version.material_id, version.pk)

    def codes(self, report):
        return [item['code'] for item in report['issues']]

    def assert_safe_failure(self, fn, code):
        with self.assertRaises(ObservationError) as raised:
            fn()
        self.assertEqual(str(raised.exception), code)
        self.assertNotIn(SENTINEL, repr(raised.exception))
        self.assertIsNone(raised.exception.__context__)
        return raised.exception

    def test_obs01_invalid_ids_no_queries(self):
        for value in (None, True, False, 0, -1, 1.0, '1', 'latest', 'all', [], {}, 2**63):
            for ids in ((value, 1), (1, value)):
                with self.subTest(ids=ids), self.assertNumQueries(0):
                    self.assert_safe_failure(lambda: observe_version_quality(self.owner, *ids), 'invalid_arguments')
        with self.assertNumQueries(0):
            self.assert_safe_failure(lambda: observe_version_quality(self.owner), 'invalid_arguments')

    def test_obs02_authentication_precedes_arguments(self):
        for user in (None, AnonymousUser()):
            with self.assertNumQueries(0):
                self.assert_safe_failure(lambda: observe_version_quality(user, True, 'all'), 'authentication_required')

    def test_obs02_unavailable_same_failure_and_selector_reused(self):
        version = self.make_version()
        self.evidence(version)
        for args in ((self.other, version.material_id, version.pk),
                     (self.owner, version.material_id + 999, version.pk),
                     (self.owner, version.material_id, version.pk + 999)):
            with self.subTest(args=args):
                self.assert_safe_failure(lambda: observe_version_quality(*args), 'object_unavailable')
        with patch.object(selectors, 'get_version', wraps=selectors.get_version) as get_version:
            self.assertEqual(self.observe(version)['assessment'], 'usable')
            get_version.assert_called_once()
        shared = self.make_version(visibility='team')
        self.evidence(shared)
        self.assertEqual(self.observe(shared, self.other)['assessment'], 'usable')

    def test_obs03_processing_priority_and_real_counts(self):
        cases = [('queued', 'pending', 'unknown', []), ('processing', 'pending', 'unknown', []),
                 ('failed', 'blocked', 'unknown', ['parse_failed']),
                 ('unexpected', 'unknown', 'unknown', ['unknown_processing_state']),
                 ('ready', 'usable', 'not_required', []),
                 ('needs_review', 'needs_review', 'not_required', ['legacy_status_needs_review'])]
        for status, assessment, review, codes in cases:
            with self.subTest(status=status):
                version = self.make_version(status=status)
                self.evidence(version)
                result = self.observe(version)
                self.assertEqual(result['assessment'], assessment)
                self.assertEqual(result['review_state'], review)
                self.assertEqual(result['processing_state'], status if status != 'unexpected' else 'unknown')
                self.assertEqual(result['counts']['evidence'], 1)
                self.assertEqual(self.codes(result), codes)

    def test_obs04_zero_all_empty_and_mixed_pdf(self):
        for texts, counts, codes in [([], (0, 0, 0), ['no_evidence']),
                                   (['', ' \t\n\r\v\f'], (2, 0, 2), ['no_text', 'page_text_missing']),
                                   (['text', ''], (2, 1, 1), ['page_text_missing'])]:
            version = self.make_version(fmt='pdf')
            for text in texts:
                self.evidence(version, text, by=True, at=True)
            result = self.observe(version)
            self.assertEqual(tuple(result['counts'][k] for k in ('evidence', 'nonempty', 'empty')), counts)
            self.assertEqual(self.codes(result), codes)
            self.assertEqual(result['review_state'], 'unknown')
            self.assertEqual(result['assessment'], 'blocked' if counts[1] == 0 else 'needs_review')

    def test_obs04_ascii_whitespace_only(self):
        version = self.make_version()
        for text in ('', '\t\n\v\f\r ', '\u00a0', '\u2003', '\u200b', ' x '):
            self.evidence(version, text)
        self.assertEqual(self.observe(version)['counts'],
                         dict(evidence=6, nonempty=4, empty=2, review_required=0, reviewed=0))

    def test_obs05_all_flag_by_at_combinations(self):
        for fmt, flag, by, at in product(('pdf', 'md'), (False, True), (False, True), (False, True)):
            with self.subTest(fmt=fmt, flag=flag, by=by, at=at):
                version = self.make_version(fmt=fmt)
                self.evidence(version, flag=flag, by=by, at=at)
                result = self.observe(version)
                incomplete = (by != at) or (fmt == 'pdf' and not flag and not (by and at)) or (flag and by and at)
                review = ('unknown' if incomplete else 'unreviewed' if flag else
                          'complete' if by and at else 'not_required')
                self.assertEqual(result['review_state'], review)
                self.assertEqual(result['counts']['reviewed'], int(by and at))
                self.assertEqual(result['counts']['review_required'], int(flag))
                self.assertEqual('review_metadata_incomplete' in self.codes(result), incomplete)
                self.assertEqual(result['assessment'], 'needs_review' if incomplete or flag else 'usable')

    def test_obs05_partial_and_overlapping_counts(self):
        version = self.make_version(fmt='pdf')
        self.evidence(version, by=True, at=True)
        self.evidence(version, flag=True)
        result = self.observe(version)
        self.assertEqual(result['review_state'], 'partial')
        self.assertEqual(result['assessment'], 'needs_review')
        self.evidence(version, flag=True, by=True, at=True)
        result = self.observe(version)
        self.assertEqual(result['counts'], dict(evidence=3, nonempty=3, empty=0, review_required=2, reviewed=2))
        self.assertEqual(result['review_state'], 'unknown')

    def test_obs06_markdown_not_required_and_empty_review_not_complete(self):
        version = self.make_version()
        self.evidence(version)
        self.assertEqual(self.observe(version)['review_state'], 'not_required')
        self.evidence(version, text='', by=True, at=True)
        result = self.observe(version)
        self.assertEqual(result['counts']['reviewed'], 1)
        self.assertEqual(result['review_state'], 'unreviewed')
        self.assertEqual(result['assessment'], 'unknown')
        self.evidence(version, by=True, at=True)
        self.assertEqual(self.observe(version)['review_state'], 'partial')

    def test_obs07_reviewed_pdf_warning_is_advisory(self):
        for status in ('ready', 'needs_review'):
            version = self.make_version(fmt='pdf', status=status, structure=False)
            self.evidence(version, by=True, at=True)
            MaterialVersion.objects.filter(pk=version.pk).update(warnings=[SENTINEL])
            result = self.observe(version)
            self.assertEqual(result['review_state'], 'complete')
            self.assertEqual(result['assessment'], 'usable' if status == 'ready' else 'needs_review')
            self.assertIn('legacy_warning_present', self.codes(result))
            self.assertIn('structure_missing', self.codes(result))

    def test_obs08_closed_dictionary_dedup_and_order(self):
        seen = {}
        for status, texts in [('unexpected', ['x']), ('failed', ['x']), ('ready', []),
                              ('ready', ['', '']), ('needs_review', ['x', 'x'])]:
            version = self.make_version(fmt='pdf', status=status, structure=False)
            MaterialVersion.objects.filter(pk=version.pk).update(warnings=[SENTINEL])
            for text in texts:
                self.evidence(version, text, flag=True, by=True, at=True)
            result = self.observe(version)
            self.assertEqual(self.codes(result), sorted(set(self.codes(result))))
            for issue in result['issues']:
                self.assertEqual(set(issue), {'code', 'severity', 'scope'})
                self.assertEqual((issue['severity'], issue['scope']), ISSUES[issue['code']])
                seen[issue['code']] = (issue['severity'], issue['scope'])
        self.assertEqual(seen, ISSUES)

    def test_obs09_exact_schema_determinism_and_single_select(self):
        version = self.make_version()
        self.evidence(version)
        with CaptureQueriesContext(connection) as queries:
            first = self.observe(version)
        self.assertEqual(len(queries), 1)
        self.assertTrue(queries[0]['sql'].lstrip().upper().startswith('SELECT'))
        self.assertEqual(set(first), {'schema_version', 'native_ref', 'processing_state', 'assessment',
                                     'review_state', 'counts', 'structure_state', 'integrity_check', 'issues'})
        self.assertEqual(first['schema_version'], 'ldb-material-quality-v1')
        self.assertEqual(first['native_ref'], {'material_id': version.material_id, 'version_id': version.pk})
        self.assertEqual(first['integrity_check'], 'not_checked')
        self.assertEqual(first['structure_state'], 'present')
        canonical = lambda r: json.dumps(r, sort_keys=True, separators=(',', ':'))
        self.assertEqual(canonical(first), canonical(self.observe(version)))

    def test_obs10_11_only_allowed_select_no_side_effects(self):
        version = self.make_version()
        self.evidence(version)
        def snapshot():
            with connection.cursor() as cursor:
                result = {}
                for table in sorted(connection.introspection.table_names()):
                    cursor.execute('SELECT * FROM ' + connection.ops.quote_name(table))
                    result[table] = sorted(map(repr, cursor.fetchall()))
                return result
        before = snapshot()
        blocked = ['builtins.open', 'apps.materials.services.parse_version',
                   'apps.materials.services.retry_version', 'apps.materials.services.review_evidence',
                   'apps.materials.structure.build_structure',
                   'apps.registry.services.register', 'apps.registry.batch.apply_batch',
                   'apps.ai.minimax.call_minimax_chat', 'apps.assistant.knowledge.search_knowledge',
                   'apps.search.evidence.search_evidence', 'urllib.request.urlopen', 'socket.socket.connect']
        with ExitStack() as stack:
            mocks = [stack.enter_context(patch(name, side_effect=AssertionError('forbidden'))) for name in blocked]
            def guard(execute, sql, params, many, context):
                self.assertTrue(sql.lstrip().upper().startswith('SELECT'))
                for forbidden in ('registry_', 'quality_', 'tasks_', 'assistant_', 'papers_', 'documents_', 'experiments_'):
                    self.assertNotIn(forbidden, sql)
                return execute(sql, params, many, context)
            with connection.execute_wrapper(guard):
                self.observe(version)
            for mock in mocks:
                mock.assert_not_called()
        self.assertEqual(before, snapshot())

    def test_obs12_no_sensitive_output_success_or_failure(self):
        version = self.make_version()
        self.evidence(version, SENTINEL)
        MaterialVersion.objects.filter(pk=version.pk).update(warnings=[SENTINEL, {'nested': SENTINEL}])
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), self.assertNoLogs():
            report = self.observe(version)
            with patch.object(selectors, 'get_version', side_effect=DatabaseError(SENTINEL)):
                self.assert_safe_failure(lambda: self.observe(version), 'observation_failed')
        self.assertNotIn(SENTINEL, json.dumps(report) + out.getvalue() + err.getvalue())

    def test_obs13_query_failure_returns_no_report_or_exception_context(self):
        version = self.make_version()
        def fail(execute, sql, params, many, context):
            raise DatabaseError(SENTINEL)
        with connection.execute_wrapper(fail):
            self.assert_safe_failure(lambda: self.observe(version), 'observation_failed')

    def test_obs13_invalid_storage_fails_closed(self):
        version = self.make_version()
        self.evidence(version)
        for changes in ({'format': 'unknown'}, {'warnings': {}}, {'warnings': 'text'}, {'warnings': 1}):
            MaterialVersion.objects.filter(pk=version.pk).update(format='md', warnings=[])
            MaterialVersion.objects.filter(pk=version.pk).update(**changes)
            self.assert_safe_failure(lambda: self.observe(version), 'observation_failed')
        MaterialVersion.objects.filter(pk=version.pk).update(format='md')
        with connection.cursor() as cursor:
            cursor.execute('UPDATE materials_materialversion SET warnings = %s WHERE id = %s', ['null', version.pk])
        self.assert_safe_failure(lambda: self.observe(version), 'observation_failed')

    def test_obs14_old_selector_and_api_unchanged(self):
        version = self.make_version(status='needs_review')
        self.evidence(version, flag=True)
        self.client.force_login(self.owner)
        url = f'/api/materials/{version.material_id}/versions/{version.pk}/'
        before = self.client.get(url)
        native_before = selectors.version_data(selectors.get_version(self.owner, version.material_id, version.pk))
        self.observe(version)
        after = self.client.get(url)
        self.assertEqual((before.status_code, before.content), (after.status_code, after.content))
        self.assertEqual(native_before, selectors.version_data(selectors.get_version(self.owner, version.material_id, version.pk)))
        self.assertEqual(native_before['retrieval_status'], 'searchable_review')

    def test_obs13_malformed_evidence_storage(self):
        version = self.make_version()
        evidence = self.evidence(version)
        original = Evidence.objects.filter(pk=evidence.pk).values().get()
        expected = self.observe(version)
        for field, value in (('review_required', 2), ('reviewed_at', 'not-a-date')):
            with self.subTest(field=field):
                if connection.vendor == 'postgresql':
                    # 类型检查先行拒绝；先退出 savepoint 再捕获，外层事务仍可查询。
                    with self.assertRaises(DatabaseError):
                        with transaction.atomic():
                            with connection.cursor() as cursor:
                                cursor.execute('UPDATE materials_evidence SET ' + field + ' = %s WHERE id = %s',
                                               [value, evidence.pk])
                    self.assertFalse(connection.needs_rollback)
                    self.assertEqual(Evidence.objects.filter(pk=evidence.pk).values().get(), original)
                    self.assertEqual(self.observe(version), expected)
                else:
                    self.assertEqual(connection.vendor, 'sqlite')
                    with connection.cursor() as cursor:
                        cursor.execute('UPDATE materials_evidence SET ' + field + ' = %s WHERE id = %s',
                                       [value, evidence.pk])
                    self.assert_safe_failure(lambda: self.observe(version), 'observation_failed')
                    Evidence.objects.filter(pk=evidence.pk).update(review_required=False, reviewed_at=None)

    def test_obs14_search_agent_and_fixed_locator_unchanged(self):
        from apps.assistant.knowledge import search_knowledge
        from apps.search.evidence import search_evidence
        version = self.make_version(status='needs_review', structure=False)
        evidence = self.evidence(version, text='Synthetic quality evidence', flag=True)
        scope = {'material_ids': [version.material_id]}
        params = {'q': 'Synthetic', 'material_id': version.material_id}
        before = (search_evidence(self.owner, params), search_knowledge(self.owner, scope, 'Synthetic'))
        self.assertTrue(before[0]['results'])
        self.assertTrue(before[1])
        self.observe(version)
        self.assertEqual(before, (search_evidence(self.owner, params), search_knowledge(self.owner, scope, 'Synthetic')))
        evidence.refresh_from_db()
        self.assertEqual((evidence.version_id, evidence.ordinal), (version.pk, 1))

    def test_frozen_synthetic_assets(self):
        manifest = json.loads((Path(__file__).parent / 'fixtures' / 'quality_observation_v1.json').read_text())
        self.assertEqual(manifest['version'], 'ldb-quality-assets-v2')
        # UTF-8、键排序、无缩进/尾随换行、不转义 Unicode；修改资产须显式复审。
        canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        self.assertEqual(hashlib.sha256(canonical).hexdigest(),
                         '11291937e968d6ca3043aa7454e3a82d185e1a983d3ff75157f3b2a4bc2380ee')
        self.assertEqual([group['id'] for group in manifest['assets']],
                         ['O01', 'O02', 'O03', 'O04', 'O05', 'O06'])
        self.assertEqual(sum(len(group['cases']) for group in manifest['assets']), 27)
        targets = set()
        for group in manifest['assets']:
            for asset in group['cases']:
                with self.subTest(group=group['id'], case=asset['id']):
                    self.assertEqual(asset['fixture_version'], manifest['version'])
                    self.assertEqual(asset['sensitive_sha256'], hashlib.sha256(SENTINEL.encode()).hexdigest())
                    target = (asset['material_id'], asset['version_id'])
                    self.assertNotIn(target, targets)
                    targets.add(target)
                    actor = self.owner if asset['permission']['actor'] == 'owner' else self.other
                    if not asset['object_exists']:
                        self.assertFalse(Material.objects.filter(pk=target[0]).exists())
                        self.assertFalse(MaterialVersion.objects.filter(pk=target[1]).exists())
                        for key in ('status', 'format', 'structure', 'raw_counts'):
                            self.assertIsNone(asset[key])
                        self.assertEqual(asset['evidence'], [])
                        self.assertEqual(asset['effective_completed_ordinals'], [])
                    else:
                        material = Material.objects.create(id=target[0], owner=self.owner, title=SENTINEL,
                                                           visibility=asset['permission']['visibility'])
                        version = MaterialVersion.objects.create(
                            id=target[1], material=material, number=1, sha256='a' * 64,
                            format=asset['format'], status=asset['status'], size=1, created_by=self.owner,
                            filename=SENTINEL, storage_key=SENTINEL, error=SENTINEL,
                            warnings=[SENTINEL] if asset['warning'] else [],
                        )
                        if asset['structure']:
                            StructureIndex.objects.create(version=version, parser_version='synthetic-v1',
                                                          source_sha256='a' * 64, is_current=True)
                        for row in asset['evidence']:
                            evidence = self.evidence(version, text=SENTINEL if row['nonempty'] else '',
                                                     flag=row['flag'], by=row['by'], at=row['at'])
                            self.assertEqual(evidence.ordinal, row['ordinal'])
                            if row['at']:
                                self.assertEqual(evidence.reviewed_at.isoformat(),
                                                 manifest['reviewed_at'].replace('Z', '+00:00'))
                        rows = asset['evidence']
                        self.assertEqual(asset['raw_counts'], {
                            'evidence': len(rows), 'nonempty': sum(r['nonempty'] for r in rows),
                            'empty': sum(not r['nonempty'] for r in rows),
                            'review_required': sum(r['flag'] for r in rows),
                            'reviewed': sum(r['by'] and r['at'] for r in rows),
                        })
                        self.assertEqual(asset['effective_completed_ordinals'], [r['ordinal'] for r in rows
                            if r['nonempty'] and not r['flag'] and r['by'] and r['at']])
                    if not asset['permission']['allowed']:
                        # 无权与不存在只冻结相同拒绝 oracle，不给可访问质量结果。
                        self.assertNotIn('expected', asset)
                        self.assertEqual(asset['expected_error'], 'object_unavailable')
                        self.assert_safe_failure(lambda: observe_version_quality(actor, *target), asset['expected_error'])
                    else:
                        result = observe_version_quality(actor, *target)
                        expected = asset['expected']
                        self.assertEqual(result['assessment'], expected['assessment'])
                        self.assertEqual(result['review_state'], expected['review_state'])
                        self.assertEqual(result['processing_state'],
                                         asset['status'] if asset['status'] != 'unexpected' else 'unknown')
                        self.assertEqual(result['counts'], asset['raw_counts'])
                        self.assertEqual(result['native_ref'], {'material_id': target[0], 'version_id': target[1]})
                        self.assertEqual(result['structure_state'], 'present' if asset['structure'] else 'missing')
                        self.assertEqual(result['issues'], [dict(code=code, severity=ISSUES[code][0], scope=ISSUES[code][1])
                                                           for code in expected['issues']])
                        self.assertNotIn(SENTINEL, json.dumps(result))

    def test_obs01_fixed_version_never_selects_latest(self):
        old = self.make_version()
        self.evidence(old, text='old')
        new = MaterialVersion.objects.create(material=old.material, number=2, sha256='b' * 64,
                                             format='pdf', status='failed', size=1, created_by=self.owner)
        self.evidence(new, text='new', flag=True)
        self.assertEqual(self.observe(old)['assessment'], 'usable')
        self.assertEqual(self.observe(new)['assessment'], 'blocked')
        self.assertEqual(self.observe(old)['counts']['review_required'], 0)
        self.assertEqual(self.observe(new)['counts']['review_required'], 1)

    def test_single_query_projection_contains_no_sensitive_selected_fields(self):
        version = self.make_version()
        self.evidence(version)
        with patch.object(selectors, 'get_version', wraps=selectors.get_version) as selector:
            self.observe(version)
        projection = selector.call_args.kwargs['queryset']
        self.assertEqual(projection.query.values_select, ('id', 'material_id', 'status', 'format'))
        self.assertFalse(projection.query.select_for_update)
        self.assertEqual(projection.query.select_related, False)
