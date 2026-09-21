import copy
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import OperationalError, connection, transaction
from django.test import TransactionTestCase, override_settings

from apps.documents.models import Document, DocumentVersion
from apps.experiments.models import ExperimentProject, ExperimentRun
from apps.materials.models import Material, MaterialVersion
from apps.papers.models import Paper
from apps.registry import batch, services
from apps.registry.models import ResearchObject, ResearchObjectBinding, ResearchRevision


@override_settings(REGISTRY_BACKFILL_ENABLED=True)
class RegistryApplyTests(TransactionTestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username='synthetic')
        self.rows = [Paper.objects.create(title=f'synthetic {i}') for i in range(3)]
        self.manifest = batch.plan_batch(kind='paper', actor_id=self.actor.pk)

    def counts(self):
        return [model.objects.count() for model in (ResearchObject, ResearchObjectBinding, ResearchRevision)]

    def seal(self, manifest):
        manifest['baseline_digest'] = services.digest(manifest['items'])
        manifest['batch_id'] = services.digest({k: v for k, v in manifest.items() if k != 'batch_id'})
        return manifest

    def test_success_and_lost_report_replay(self):
        before = copy.deepcopy(self.manifest)
        result = batch.apply_batch(self.manifest)
        self.assertEqual(result['status'], 'committed')
        self.assertEqual(result['committed_cursor'], self.manifest['scan_cursor'])
        self.assertEqual(result['summary']['created'], 3)
        self.assertEqual(self.counts(), [3, 3, 3])
        identities = [(i['object_id'], i['revision_id']) for i in result['items']]
        # No report/receipt persistence is needed to recover a lost first response.
        replay = batch.apply_batch(self.manifest)
        self.assertEqual(replay['summary']['unchanged'], 3)
        self.assertEqual([(i['object_id'], i['revision_id']) for i in replay['items']], identities)
        self.assertEqual(self.counts(), [3, 3, 3])
        self.assertEqual(self.manifest, before)
        for object_id, _ in identities:
            self.assertEqual(services.check_invariants(object_id), [])

    def test_disabled_and_missing_switch(self):
        for enabled in (False, None):
            with self.subTest(enabled=enabled), override_settings(REGISTRY_BACKFILL_ENABLED=enabled):
                with self.assertRaises(batch.ApplyError) as caught:
                    batch.apply_batch(self.manifest)
                self.assertEqual(caught.exception.code, 'backfill_disabled')
        with override_settings():
            from django.conf import settings
            del settings.REGISTRY_BACKFILL_ENABLED
            with self.assertRaises(batch.ApplyError) as caught:
                batch.apply_batch(self.manifest)
            self.assertEqual(caught.exception.code, 'backfill_disabled')
        self.assertEqual(self.counts(), [0, 0, 0])

    def test_second_failure_rolls_back_without_ids_or_cursor(self):
        original = services.register
        calls = []
        def failing(*args, **kwargs):
            calls.append(args)
            if len(calls) == 2:
                raise services.RegistryError('source_deleted')
            return original(*args, **kwargs)
        with patch.object(services, 'register', side_effect=failing):
            result = batch.apply_batch(self.manifest)
        self.assertEqual(result['status'], 'rolled_back')
        self.assertIsNone(result['committed_cursor'])
        self.assertEqual([i['status'] for i in result['items']], ['rolled_back', 'failed', 'not_attempted'])
        self.assertEqual(result['items'][1]['reason'], 'source_deleted')
        self.assertEqual(result['summary']['created'], 0)
        self.assertEqual(result['summary']['unchanged'], 0)
        self.assertNotIn('object_id', services.canonical(result['items']))
        self.assertNotIn('revision_id', services.canonical(result['items']))
        self.assertEqual(self.counts(), [0, 0, 0])

    def test_source_drift_rolls_back(self):
        Paper.objects.filter(pk=self.rows[1].pk).update(title='changed')
        result = batch.apply_batch(self.manifest)
        self.assertEqual(result['items'][1]['reason'], 'stale')
        self.assertEqual(self.counts(), [0, 0, 0])
        self.assertIsNone(result['committed_cursor'])

    def test_target_mismatch_and_tampered_digest(self):
        for field, value, reason in [('target_fingerprint', '0' * 64, 'target_mismatch'),
                                     ('batch_id', '0' * 64, 'invalid_manifest')]:
            manifest = copy.deepcopy(self.manifest)
            manifest[field] = value
            if field != 'batch_id':
                self.seal(manifest)
            with self.assertRaises(batch.ApplyError) as caught:
                batch.apply_batch(manifest)
            self.assertEqual(caught.exception.code, reason)
        self.assertEqual(self.counts(), [0, 0, 0])

    def test_resealed_malformed_manifests_rejected_before_register(self):
        mutations = [
            lambda m: m.update(schema_version='registry-plan-v1'),
            lambda m: m.update(code_version='registry-plan-1'),
            lambda m: m.update(extra='PRIVATE_SENTINEL'),
            lambda m: m.update(mode='apply'),
            lambda m: m.update(items=[]),
            lambda m: m.update(items=m['items'] * 17),
            lambda m: m['scope'].update(limit=51),
            lambda m: m['scope'].update(actor_id=True),
            lambda m: m['scope'].update(extra=1),
            lambda m: m['scope'].update(cutoff='2026-01-01'),
            lambda m: m['scope'].update(after_pk=m['scope']['through_pk']),
            lambda m: m['items'][0].update(legacy_model='document'),
            lambda m: m['items'][0].update(actor_id=999),
            lambda m: m['items'][0].update(legacy_pk=True),
            lambda m: m['items'][0].update(version_id=1),
            lambda m: m['items'][0].update(status='rejected', reason='source_deleted'),
            lambda m: m['items'][0].update(source_revision_id='PRIVATE_SENTINEL'),
            lambda m: m['items'][0].update(research_object_id='PRIVATE_SENTINEL'),
            lambda m: m['items'][0].update(expected_current_revision_id='PRIVATE_SENTINEL'),
            lambda m: m['items'][0].update(observation_sha256='PRIVATE_SENTINEL'),
            lambda m: m['items'][0].update(operation_key='PRIVATE_SENTINEL'),
            lambda m: m['items'][0].update(extra='PRIVATE_SENTINEL'),
            lambda m: m['items'].reverse(),
            lambda m: m['items'][1].update(legacy_pk=m['items'][0]['legacy_pk']),
            lambda m: m['summary'].update(scanned=True),
            lambda m: m['summary'].update(created=1),
            lambda m: m.update(scan_cursor=0),
            lambda m: m.update(has_more=1),
        ]
        for mutate in mutations:
            manifest = copy.deepcopy(self.manifest)
            mutate(manifest)
            self.seal(manifest)
            with self.subTest(manifest=manifest), patch.object(services, 'register') as register:
                with self.assertRaises(batch.ApplyError) as caught:
                    batch.apply_batch(manifest)
                self.assertEqual(caught.exception.code, 'invalid_manifest')
                register.assert_not_called()

    def test_no_replan_and_report_after_actual_commit(self):
        with patch.object(services, 'plan_registration', side_effect=AssertionError('no replan')):
            result = batch.apply_batch(self.manifest)
        self.assertFalse(connection.in_atomic_block)
        self.assertTrue(connection.get_autocommit())
        self.assertEqual(result['status'], 'committed')
        with transaction.atomic():
            with self.assertRaises(batch.ApplyError) as caught:
                batch.apply_batch(self.manifest)
            self.assertEqual(caught.exception.code, 'outer_transaction_required')

    def test_unknown_failure_redacted(self):
        with patch.object(services, 'register', side_effect=RuntimeError('PRIVATE_SENTINEL DSN SQL')):
            result = batch.apply_batch(self.manifest)
        self.assertEqual(result['items'][0]['reason'], 'unexpected_error')
        self.assertNotIn('PRIVATE_SENTINEL', services.canonical(result))
        self.assertEqual(self.counts(), [0, 0, 0])

    def test_five_kinds_success_and_replay(self):
        material = Material.objects.create(title='synthetic', owner=self.actor)
        MaterialVersion.objects.create(material=material, number=1, sha256='1' * 64,
            filename='synthetic', storage_key='synthetic', format='md', size=3, created_by=self.actor)
        document = Document.objects.create(title='synthetic')
        DocumentVersion.objects.create(document=document, version=1, markdown='synthetic')
        project = ExperimentProject.objects.create(title='synthetic', owner=self.actor)
        ExperimentRun.objects.create(project=project, notes='synthetic')
        for kind in services.MODELS:
            with self.subTest(kind=kind):
                manifest = batch.plan_batch(kind=kind, actor_id=self.actor.pk, limit=1)
                first = batch.apply_batch(manifest)
                self.assertEqual(first['summary'], dict(created=1, unchanged=0))
                second = batch.apply_batch(manifest)
                self.assertEqual(second['summary'], dict(created=0, unchanged=1))
                self.assertEqual(first['items'][0]['object_id'], second['items'][0]['object_id'])
                self.assertEqual(first['items'][0]['revision_id'], second['items'][0]['revision_id'])
                self.assertEqual(services.check_invariants(first['items'][0]['object_id']), [])
        self.assertEqual(self.counts(), [5, 5, 5])

    def test_fifty_items_success(self):
        Paper.objects.bulk_create([Paper(title=f'synthetic {i}', slug=f'apply-bound-{i}') for i in range(47)])
        manifest = batch.plan_batch(kind='paper', actor_id=self.actor.pk, limit=50)
        result = batch.apply_batch(manifest)
        self.assertEqual(result['summary'], dict(created=50, unchanged=0))
        self.assertEqual(self.counts(), [50, 50, 50])

    def test_fingerprint_uses_current_name_without_disclosure(self):
        original = batch._target_fingerprint()
        for changes in ({'NAME': 'PRIVATE_SENTINEL_DB'}, {'HOST': 'PRIVATE_SENTINEL_HOST'},
                        {'PORT': '6543'}, {'ENGINE': 'PRIVATE_SENTINEL_ENGINE'}):
            with self.subTest(changes=changes), patch.dict(connection.settings_dict, changes):
                changed = batch._target_fingerprint()
                self.assertNotEqual(original, changed)
                self.assertNotIn('PRIVATE_SENTINEL', changed)
                with self.assertRaises(batch.ApplyError) as caught:
                    batch.apply_batch(self.manifest)
                self.assertEqual(caught.exception.code, 'target_mismatch')
        with patch.dict(connection.settings_dict, USER='PRIVATE_SENTINEL_USER',
                        PASSWORD='PRIVATE_SENTINEL_PASSWORD', OPTIONS={'secret': 'PRIVATE_SENTINEL'}):
            self.assertEqual(original, batch._target_fingerprint())
        # SQLite 使用已打开的测试连接；HOST 不选择连接，仅参与当前目标标识。
        with patch.dict(connection.settings_dict, HOST='PRIVATE_SENTINEL_HOST'):
            manifest = batch.plan_batch(kind='paper', actor_id=self.actor.pk)
            report = batch.apply_batch(manifest)
            self.assertEqual(report['status'], 'committed')
            self.assertNotIn('PRIVATE_SENTINEL', services.canonical(manifest))
            self.assertNotIn('PRIVATE_SENTINEL', services.canonical(report))
        for field in ('target_fingerprint', 'code_version', 'baseline_digest'):
            manifest = copy.deepcopy(self.manifest)
            manifest[field] = '0' * 64
            with self.assertRaises(batch.ApplyError):
                batch.apply_batch(manifest)
        self.assertEqual(self.counts(), [3, 3, 3])

    def test_commit_failure_reports_unknown_without_ids_or_progress(self):
        with patch.object(connection, 'commit', side_effect=OperationalError('PRIVATE_SENTINEL')):
            result = batch.apply_batch(self.manifest)
        self.assertEqual(result['status'], 'commit_unknown')
        self.assertEqual(result['reason'], 'commit_unknown')
        self.assertEqual([i['status'] for i in result['items']], ['commit_unknown'] * 3)
        self.assertEqual(result['summary'], dict(created=0, unchanged=0))
        self.assertIsNone(result['committed_cursor'])
        self.assertNotIn('object_id', services.canonical(result))
        self.assertNotIn('revision_id', services.canonical(result))
        self.assertNotIn('PRIVATE_SENTINEL', services.canonical(result))
        self.assertEqual(self.counts(), [0, 0, 0])
        # SQLite 已知回滚不代表其他数据库可确定提交结果；仅人工原样重放恢复。
        replay = batch.apply_batch(self.manifest)
        self.assertEqual(replay['status'], 'committed')

    def test_manual_transaction_rejected(self):
        connection.set_autocommit(False)
        try:
            with self.assertRaises(batch.ApplyError) as caught:
                batch.apply_batch(self.manifest)
            self.assertEqual(caught.exception.code, 'outer_transaction_required')
        finally:
            connection.rollback()
            connection.set_autocommit(True)
        self.assertEqual(self.counts(), [0, 0, 0])

    def test_existing_object_identity_checked(self):
        batch.apply_batch(self.manifest)
        manifest = batch.plan_batch(kind='paper', actor_id=self.actor.pk)
        manifest['items'][1]['research_object_id'] = manifest['items'][0]['research_object_id']
        self.seal(manifest)
        result = batch.apply_batch(manifest)
        self.assertEqual(result['status'], 'rolled_back')
        self.assertEqual(result['items'][1]['reason'], 'object_conflict')
        self.assertEqual(result['summary'], dict(created=0, unchanged=0))
        self.assertEqual(self.counts(), [3, 3, 3])
