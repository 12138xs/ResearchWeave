import io
import json
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone as utc
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models.query import QuerySet
from django.test import TestCase, override_settings

from apps.documents.models import Document, DocumentVersion
from apps.experiments.models import ExperimentProject, ExperimentRun
from apps.materials.models import Material, MaterialVersion
from apps.papers.models import Paper
from apps.registry import services
from apps.registry.models import ResearchObject, ResearchObjectBinding, ResearchRevision


class RegistryPlanTests(TestCase):
    def setUp(self):
        self.cutoff = datetime(2026, 1, 2, tzinfo=utc.utc)
        self.earlier = self.cutoff - timedelta(days=1)
        self.actor = get_user_model().objects.create_user(username='PRIVATE_SENTINEL')
        self.material = Material.objects.create(title='PRIVATE_SENTINEL', owner=self.actor)
        self.document = Document.objects.create(title='PRIVATE_SENTINEL', summary='PRIVATE_SENTINEL')
        self.paper = Paper.objects.create(title='PRIVATE_SENTINEL', abstract='PRIVATE_SENTINEL', source_pdf_path='PRIVATE_SENTINEL')
        self.project = ExperimentProject.objects.create(title='PRIVATE_SENTINEL', owner=self.actor, protocol_markdown='PRIVATE_SENTINEL')
        self.run = ExperimentRun.objects.create(project=self.project, notes='PRIVATE_SENTINEL', params_json={'key': 'PRIVATE_SENTINEL'})
        self.rows = {'material': self.material, 'document': self.document, 'paper': self.paper,
                     'experiment_project': self.project, 'experiment_run': self.run}
        for model in (Paper, ExperimentProject, ExperimentRun):
            model.objects.all().update(updated_at=self.earlier)
        self.mv = self.version('material', 1)
        self.dv = self.version('document', 1)

    def version(self, kind, number, when=None):
        if kind == 'material':
            row = MaterialVersion.objects.create(material=self.material, number=number,
                sha256=f'{number:064x}', filename='PRIVATE_SENTINEL', storage_key='PRIVATE_SENTINEL',
                format='md', size=3, created_by=self.actor)
        else:
            row = DocumentVersion.objects.create(document=self.document, version=number, markdown='PRIVATE_SENTINEL')
        type(row).objects.filter(pk=row.pk).update(created_at=when or self.earlier)
        return row

    def plan(self, kind='paper', **changes):
        from apps.registry.batch import plan_batch
        args = dict(kind=kind, actor_id=self.actor.pk, cutoff=self.cutoff.isoformat())
        args.update(changes)
        return plan_batch(**args)

    def command(self, **changes):
        out = io.StringIO()
        args = dict(kind='paper', actor_id=self.actor.pk, cutoff=self.cutoff.isoformat(), stdout=out)
        args.update(changes)
        call_command('registry_plan', **args)
        return args['stdout'].getvalue()

    def tables(self):
        return [list(model.objects.order_by('pk').values()) for model in (
            Material, Document, Paper, ExperimentProject, ExperimentRun, MaterialVersion,
            DocumentVersion, ResearchObject, ResearchObjectBinding, ResearchRevision)]

    def test_five_kinds_whitelist_and_summary(self):
        allowed = {'legacy_model', 'legacy_pk', 'version_id', 'actor_id', 'source_revision_id',
                   'observation_sha256', 'expected_current_revision_id', 'research_object_id',
                   'operation_key', 'status', 'reason'}
        for kind, row in self.rows.items():
            with self.subTest(kind=kind):
                result = self.plan(kind)
                self.assertEqual(result['schema_version'], 'registry-plan-v1')
                self.assertEqual(result['mode'], 'dry-run')
                self.assertEqual(result['summary'], {'scanned': 1, 'planned': 1, 'rejected': 0, 'created': 0})
                item = result['items'][0]
                self.assertEqual(set(item), allowed)
                self.assertEqual((item['legacy_model'], item['legacy_pk']), (kind, row.pk))
                self.assertEqual(item['status'], 'planned')
                self.assertIsNone(item['reason'])
                self.assertIsNone(item['source_revision_id'])
                self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))
                self.assertNotIn('would_create', result['summary'])
                self.assertFalse(result['has_more'])

    def test_fixed_cutoff_max_version_and_pk_order(self):
        for kind, model, field in [('material', MaterialVersion, 'number'), ('document', DocumentVersion, 'version')]:
            with self.subTest(kind=kind):
                self.version(kind, 3, self.cutoff + timedelta(seconds=1))
                eligible = self.version(kind, 2, self.cutoff)
                calls = []
                original = QuerySet.order_by
                def spy(queryset, *fields):
                    if queryset.model is model:
                        calls.append(fields)
                    return original(queryset, *fields)
                # Legacy uniqueness prevents equal-version fixtures; inspect the tie-break sort.
                with patch.object(QuerySet, 'order_by', autospec=True, side_effect=spy):
                    result = self.plan(kind)
                self.assertEqual(result['items'][0]['version_id'], eligible.pk)
                self.assertIn(('-' + field, '-pk'), calls)

    def test_no_eligible_version_rejected(self):
        for kind, model in [('material', MaterialVersion), ('document', DocumentVersion)]:
            with self.subTest(kind=kind):
                model.objects.all().update(created_at=self.cutoff + timedelta(seconds=1))
                result = self.plan(kind)
                self.assertEqual(result['items'][0]['reason'], 'fixed_version_required')
                self.assertEqual(result['items'][0]['status'], 'rejected')
                self.assertIsNone(result['items'][0]['version_id'])
                self.assertEqual(result['summary'], {'scanned': 1, 'planned': 0, 'rejected': 1, 'created': 0})

    def test_baseline_cutoff_inclusive(self):
        for kind in ('paper', 'experiment_project', 'experiment_run'):
            row = self.rows[kind]
            type(row).objects.filter(pk=row.pk).update(updated_at=self.cutoff)
            self.assertEqual(self.plan(kind)['summary']['planned'], 1)
            type(row).objects.filter(pk=row.pk).update(updated_at=self.cutoff + timedelta(microseconds=1))
            self.assertEqual(self.plan(kind)['summary']['scanned'], 0)

    def test_pages_freeze_upper_bound_without_gaps_or_duplicates(self):
        rows = [self.paper] + [Paper.objects.create(title=f'synthetic {i}') for i in range(4)]
        Paper.objects.all().update(updated_at=self.earlier)
        first = self.plan(limit=2)
        upper = first['scope']['through_pk']
        new = Paper.objects.create(title='later insert')
        Paper.objects.filter(pk=new.pk).update(updated_at=self.earlier)
        second = self.plan(after_pk=first['scan_cursor'], through_pk=upper, limit=2)
        third = self.plan(after_pk=second['scan_cursor'], through_pk=upper, limit=2)
        ids = [item['legacy_pk'] for page in (first, second, third) for item in page['items']]
        self.assertEqual(ids, [row.pk for row in rows])
        self.assertEqual([p['has_more'] for p in (first, second, third)], [True, True, False])
        empty = self.plan(after_pk=upper, through_pk=upper)
        self.assertEqual(empty['items'], [])
        self.assertFalse(empty['has_more'])
        self.assertEqual(empty['scan_cursor'], upper)
        self.assertEqual(empty['summary'], {'scanned': 0, 'planned': 0, 'rejected': 0, 'created': 0})

    def test_rejected_items_advance_cursor(self):
        self.mv.delete()
        extra = Material.objects.create(title='synthetic empty', owner=self.actor)
        first = self.plan('material', limit=1)
        self.assertEqual(first['scan_cursor'], self.material.pk)
        self.assertTrue(first['has_more'])
        second = self.plan('material', after_pk=first['scan_cursor'], through_pk=extra.pk, limit=1)
        self.assertEqual(second['scan_cursor'], extra.pk)
        self.assertEqual(second['summary']['rejected'], 1)

    def test_stable_json_and_zero_changes_for_all_tables(self):
        p = services.plan_registration('paper', self.paper.pk, actor_id=self.actor.pk)
        with override_settings(REGISTRY_BACKFILL_ENABLED=True):
            services.register('paper', self.paper.pk, actor_id=self.actor.pk,
                operation_key=p['operation_key'], expected_observation_sha256=p['observation_sha256'],
                expected_current_revision_id=p['expected_current_revision_id'])
        before = self.tables()
        with patch.object(services, 'register', side_effect=AssertionError('must not write')):
            for kind in self.rows:
                with self.subTest(kind=kind):
                    one = self.command(kind=kind)
                    self.assertEqual(one, self.command(kind=kind))
                    data = json.loads(one)
                    self.assertEqual(one, services.canonical(data) + '\n')
                    self.assertEqual(len(data['batch_id']), 64)
                    self.assertEqual(len(data['baseline_digest']), 64)
                    self.assertEqual(self.tables(), before)

    def test_defaults_and_normalized_cutoff(self):
        from apps.registry.batch import plan_batch
        with patch('apps.registry.batch.timezone.now', return_value=self.cutoff) as now:
            result = plan_batch(kind='paper', actor_id=self.actor.pk)
        now.assert_called_once()
        self.assertEqual(result['scope']['cutoff'], '2026-01-02T00:00:00.000000Z')
        self.assertEqual(result['scope']['after_pk'], 0)
        self.assertEqual(result['scope']['limit'], 20)
        self.assertEqual(result['scope']['through_pk'], self.paper.pk)
        self.assertEqual(result, self.plan(cutoff='2026-01-02T08:00:00+08:00'))
        self.assertEqual(self.plan(limit=50)['scope']['limit'], 50)

    def test_invalid_arguments_exit_two_without_writes(self):
        cases = [dict(kind='unknown'), dict(actor_id=999999), dict(actor_id=0), dict(actor_id=True),
                 dict(after_pk=-1), dict(through_pk=-1), dict(after_pk=2, through_pk=1),
                 dict(limit=0), dict(limit=51), dict(limit=True), dict(limit='PRIVATE_SENTINEL'),
                 dict(cutoff='invalid'), dict(cutoff='2026-01-02'), dict(cutoff='2026-01-02T00:00:00'),
                 dict(after_pk=2**63), dict(cutoff='2026-99-99T00:00:00Z')]
        before = self.tables()
        for changes in cases:
            with self.subTest(changes=changes):
                with self.assertRaises(CommandError) as caught:
                    self.command(**changes)
                self.assertEqual(caught.exception.returncode, 2)
                self.assertNotIn('PRIVATE_SENTINEL', str(caught.exception))
                self.assertEqual(self.tables(), before)

    def test_reason_whitelist_and_unknown_exception_redaction(self):
        with patch.object(services, 'plan_registration', side_effect=services.RegistryError('source_deleted')):
            result = self.plan()
        self.assertEqual(result['items'][0]['reason'], 'source_deleted')
        for error in (RuntimeError('PRIVATE_SENTINEL DSN SQL'), services.RegistryError('PRIVATE_SENTINEL')):
            out = io.StringIO()
            with patch.object(services, 'plan_registration', side_effect=error):
                with self.assertRaises(CommandError) as caught:
                    self.command(stdout=out)
            self.assertEqual(caught.exception.returncode, 2)
            self.assertEqual(str(caught.exception), 'unexpected_error')
            self.assertEqual(out.getvalue(), '')

    def test_cli_parser_errors_redact_raw_input(self):
        from apps.registry.management.commands.registry_plan import Command
        for argv in (['--kind', 'paper'], ['--all=PRIVATE_SENTINEL'], ['--kind']):
            stderr = io.StringIO()
            with redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
                Command().run_from_argv(['manage.py', 'registry_plan', *argv])
            self.assertEqual(caught.exception.code, 2)
            self.assertNotIn('PRIVATE_SENTINEL', stderr.getvalue())
            self.assertIn('invalid_arguments', stderr.getvalue())

    def test_actual_command_entrypoint_success_and_failure(self):
        from apps.registry.management.commands.registry_plan import Command
        out, err = io.StringIO(), io.StringIO()
        Command(stdout=out, stderr=err).run_from_argv([
            'manage.py', 'registry_plan', '--kind', 'paper', '--actor-id', str(self.actor.pk),
            '--cutoff', self.cutoff.isoformat()])
        self.assertEqual(err.getvalue(), '')
        self.assertEqual(json.loads(out.getvalue())['summary']['planned'], 1)
        out, err = io.StringIO(), io.StringIO()
        with patch.object(services, 'plan_registration', side_effect=RuntimeError('PRIVATE_SENTINEL')):
            with self.assertRaises(SystemExit) as caught:
                Command(stdout=out, stderr=err).run_from_argv([
                    'manage.py', 'registry_plan', '--kind', 'paper', '--actor-id', str(self.actor.pk),
                    '--cutoff', self.cutoff.isoformat()])
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(out.getvalue(), '')
        self.assertEqual(err.getvalue(), 'CommandError: unexpected_error\n')

    def test_empty_source_and_hard_page_size(self):
        Paper.objects.all().delete()
        empty = self.plan()
        self.assertEqual(empty['scope']['through_pk'], 0)
        self.assertEqual(empty['scan_cursor'], 0)
        self.assertEqual(empty['summary']['scanned'], 0)
        self.assertFalse(empty['has_more'])
        Paper.objects.bulk_create([Paper(title='PRIVATE_SENTINEL', slug=f'bounded-{i}') for i in range(55)])
        Paper.objects.all().update(updated_at=self.earlier)
        result = self.plan(limit=50)
        self.assertEqual(len(result['items']), 50)
        self.assertEqual(result['summary']['scanned'], 50)
        self.assertTrue(result['has_more'])
        self.assertEqual(len(self.plan()['items']), 20)

    def test_scope_and_source_change_digest(self):
        one = self.plan()
        limited = self.plan(limit=1)
        self.assertNotEqual(one['batch_id'], limited['batch_id'])
        Paper.objects.filter(pk=self.paper.pk).update(year=2025)
        changed = self.plan()
        self.assertNotEqual(one['baseline_digest'], changed['baseline_digest'])
        self.assertNotEqual(one['batch_id'], changed['batch_id'])

    def test_plan_service_called_with_only_frozen_ids_and_extra_fields_dropped(self):
        original = services.plan_registration
        seen = []
        def extra(*args, **kwargs):
            seen.append((args, kwargs))
            return dict(original(*args, **kwargs), title='PRIVATE_SENTINEL', snapshot='PRIVATE_SENTINEL')
        with patch.object(services, 'plan_registration', side_effect=extra):
            result = self.plan('material')
        self.assertEqual(seen, [(('material', self.material.pk),
                                {'actor_id': self.actor.pk, 'version_id': self.mv.pk, 'source_revision_id': None})])
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))

    def test_mixed_results_preserve_count_conservation(self):
        other = Material.objects.create(title='no versions', owner=self.actor)
        result = self.plan('material')
        self.assertEqual([i['legacy_pk'] for i in result['items']], [self.material.pk, other.pk])
        self.assertEqual(result['summary'], {'scanned': 2, 'planned': 1, 'rejected': 1, 'created': 0})
