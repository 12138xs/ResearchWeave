import io
import json
import uuid
from contextlib import redirect_stderr
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.documents.models import Document, DocumentVersion
from apps.experiments.models import ExperimentProject, ExperimentRun
from apps.materials.models import Material, MaterialVersion
from apps.papers.models import Paper
from apps.registry import services
from apps.registry.models import ResearchObject, ResearchObjectBinding, ResearchRevision


class RegistryAuditTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username='PRIVATE_SENTINEL')
        self.paper = Paper.objects.create(title='PRIVATE_SENTINEL', abstract='PRIVATE_SENTINEL')
        self.obj = self.register(self.paper)

    def register(self, paper):
        plan = services.plan_registration('paper', paper.pk, actor_id=self.actor.pk)
        with override_settings(REGISTRY_BACKFILL_ENABLED=True):
            services.register('paper', paper.pk, actor_id=self.actor.pk,
                operation_key=plan['operation_key'],
                expected_observation_sha256=plan['observation_sha256'],
                expected_current_revision_id=plan['expected_current_revision_id'])
        return ResearchObjectBinding.objects.get(paper=paper).research_object

    def audit(self, ids):
        from apps.registry.batch import audit_objects
        return audit_objects(ids)

    def command(self, ids, code=0):
        out = io.StringIO()
        if code:
            with self.assertRaises(CommandError) as caught:
                call_command('registry_audit', object_id=ids, stdout=out)
            self.assertEqual(caught.exception.returncode, code)
        else:
            call_command('registry_audit', object_id=ids, stdout=out)
        return out.getvalue()

    def tables(self):
        return [list(model.objects.order_by('pk').values()) for model in (
            Material, Document, Paper, ExperimentProject, ExperimentRun, MaterialVersion,
            DocumentVersion, ResearchObject, ResearchObjectBinding, ResearchRevision)]

    def test_clean_manifest(self):
        result = json.loads(self.command([str(self.obj.pk)]))
        self.assertEqual(set(result), {'schema_version', 'mode', 'code_version', 'batch_id', 'items', 'summary'})
        self.assertEqual(result['schema_version'], 'registry-audit-v1')
        self.assertEqual(result['mode'], 'audit')
        self.assertEqual(result['items'], [{'object_id': str(self.obj.pk), 'status': 'ok', 'reasons': []}])
        self.assertEqual(result['summary'], dict(requested=1, checked=1, ok=1, with_findings=0, unavailable=0, writes=0))

    def test_missing_is_complete_finding(self):
        missing = str(uuid.uuid4())
        result = json.loads(self.command([str(self.obj.pk), missing], code=3))
        self.assertIn(dict(object_id=missing, status='unavailable', reasons=['object_unavailable']), result['items'])
        self.assertEqual(result['summary'], dict(requested=2, checked=1, ok=1, with_findings=0, unavailable=1, writes=0))

    def test_normalization_order_and_hash(self):
        other = self.register(Paper.objects.create(title='PRIVATE_SENTINEL'))
        one = self.command([str(self.obj.pk).upper(), other.pk.hex])
        two = self.command([str(other.pk), str(self.obj.pk)])
        self.assertEqual(one, two)
        result = json.loads(one)
        self.assertEqual(one, services.canonical(result) + '\n')
        batch_id = result.pop('batch_id')
        self.assertEqual(batch_id, services.digest(result))
        self.assertEqual([i['object_id'] for i in result['items']], sorted([str(self.obj.pk), str(other.pk)]))
        self.assertNotIn('PRIVATE_SENTINEL', one)

    def test_orphan_is_not_skipped(self):
        ResearchObjectBinding.objects.filter(research_object=self.obj).delete()
        result = json.loads(self.command([str(self.obj.pk)], code=3))
        self.assertEqual(result['items'][0]['reasons'], ['source_deleted'])
        self.assertEqual(result['summary']['with_findings'], 1)

    def test_snapshot_hash_cycle_and_current_ownership(self):
        other = self.register(Paper.objects.create(title='other'))
        ResearchRevision.objects.filter(pk=self.obj.current_revision_id).update(
            content_sha256='0' * 64, source_revision_id=self.obj.current_revision_id)
        ResearchObject.objects.filter(pk=self.obj.pk).update(current_revision_id=other.current_revision_id)
        result = self.audit([str(self.obj.pk)])
        self.assertEqual(result['items'][0]['reasons'],
                         ['current_ownership_mismatch', 'snapshot_hash_mismatch', 'source_cycle'])

    def test_snapshot_schema_and_stale(self):
        ResearchRevision.objects.filter(pk=self.obj.current_revision_id).update(snapshot={'private': 'PRIVATE_SENTINEL'})
        Paper.objects.filter(pk=self.paper.pk).update(title='changed')
        self.assertEqual(self.audit([str(self.obj.pk)])['items'][0]['reasons'], ['snapshot_schema_mismatch', 'stale'])

    def test_binding_type_mismatch(self):
        ResearchObject.objects.filter(pk=self.obj.pk).update(object_type='document')
        self.assertEqual(self.audit([str(self.obj.pk)])['items'][0]['reasons'], ['binding_type_mismatch'])

    def test_fixed_version_content_changed(self):
        document = Document.objects.create(title='PRIVATE_SENTINEL')
        version = DocumentVersion.objects.create(document=document, version=1, markdown='original')
        plan = services.plan_registration('document', document.pk, actor_id=self.actor.pk, version_id=version.pk)
        with override_settings(REGISTRY_BACKFILL_ENABLED=True):
            services.register('document', document.pk, actor_id=self.actor.pk, version_id=version.pk,
                operation_key=plan['operation_key'], expected_observation_sha256=plan['observation_sha256'],
                expected_current_revision_id=plan['expected_current_revision_id'])
        obj = ResearchObjectBinding.objects.get(document=document).research_object
        DocumentVersion.objects.filter(pk=version.pk).update(markdown='PRIVATE_SENTINEL changed')
        self.assertIn('fixed_content_changed', self.audit([str(obj.pk)])['items'][0]['reasons'])

    def test_invalid_inputs_prevalidated(self):
        cases = [([], 'invalid_object_ids'), ([str(uuid.uuid4()) for _ in range(51)], 'invalid_object_ids'),
                 (['PRIVATE_SENTINEL'], 'invalid_object_id'), ([None], 'invalid_object_id'),
                 ([str(self.obj.pk), self.obj.pk.hex.upper()], 'duplicate_object_id')]
        for ids, reason in cases:
            with self.subTest(reason=reason), patch.object(services, 'check_invariants') as checker:
                out = io.StringIO()
                with self.assertRaises(CommandError) as caught:
                    call_command('registry_audit', object_id=ids, stdout=out)
                self.assertEqual(caught.exception.returncode, 2)
                self.assertEqual(str(caught.exception), reason)
                self.assertEqual(out.getvalue(), '')
                checker.assert_not_called()

    def test_fifty_explicit_ids(self):
        ids = [str(uuid.uuid4()) for _ in range(50)]
        result = json.loads(self.command(ids, code=3))
        self.assertEqual(len(result['items']), 50)
        self.assertEqual(result['summary']['unavailable'], 50)

    def test_stable_reason_passthrough_deduplicated(self):
        # Adapter contract only: the existing checker does not discover every reason itself.
        with patch.object(services, 'check_invariants', return_value=[
                'source_revision_unavailable', 'source_cycle', 'source_cycle']):
            self.assertEqual(self.audit([str(self.obj.pk)])['items'][0]['reasons'],
                             ['source_cycle', 'source_revision_unavailable'])

    def test_unknown_exception_or_reason_has_no_partial_json(self):
        ids = [str(self.obj.pk), str(uuid.uuid4())]
        for failure in (RuntimeError('PRIVATE_SENTINEL DSN SQL'),
                        services.RegistryError('PRIVATE_SENTINEL'), ['PRIVATE_SENTINEL'],
                        Document.DoesNotExist('PRIVATE_SENTINEL')):
            with self.subTest(failure=type(failure).__name__):
                out = io.StringIO()
                with patch.object(services, 'check_invariants', side_effect=[[], failure]):
                    with self.assertRaises(CommandError) as caught:
                        call_command('registry_audit', object_id=ids, stdout=out)
                self.assertEqual(caught.exception.returncode, 2)
                self.assertEqual(str(caught.exception), 'unexpected_error')
                self.assertEqual(out.getvalue(), '')

    def test_ten_tables_unchanged_and_no_plan_or_register(self):
        material = Material.objects.create(title='PRIVATE_SENTINEL', owner=self.actor)
        MaterialVersion.objects.create(material=material, number=1, sha256='1' * 64,
            filename='PRIVATE_SENTINEL', storage_key='PRIVATE_SENTINEL', format='md', size=3, created_by=self.actor)
        document = Document.objects.create(title='PRIVATE_SENTINEL')
        DocumentVersion.objects.create(document=document, version=1, markdown='PRIVATE_SENTINEL')
        project = ExperimentProject.objects.create(title='PRIVATE_SENTINEL', owner=self.actor)
        ExperimentRun.objects.create(project=project, notes='PRIVATE_SENTINEL')
        ResearchRevision.objects.filter(pk=self.obj.current_revision_id).update(content_sha256='0' * 64)
        before = self.tables()
        with patch.object(services, 'plan_registration', side_effect=AssertionError('no planning')), \
                patch.object(services, 'register', side_effect=AssertionError('no writing')):
            for ids, code in [([str(self.obj.pk)], 3), ([str(uuid.uuid4())], 3)]:
                self.assertEqual(self.command(ids, code), self.command(ids, code))
                self.assertEqual(self.tables(), before)

    def test_cli_exit_codes_and_parser_redaction(self):
        from apps.registry.management.commands.registry_audit import Command
        for ids, expected in [([str(self.obj.pk)], 0), ([str(uuid.uuid4())], 3), (['PRIVATE_SENTINEL'], 2)]:
            out, err = io.StringIO(), io.StringIO()
            argv = ['manage.py', 'registry_audit', '--object-id', ids[0]]
            command = Command(stdout=out, stderr=err)
            if expected:
                with self.assertRaises(SystemExit) as caught:
                    command.run_from_argv(argv)
                self.assertEqual(caught.exception.code, expected)
            else:
                command.run_from_argv(argv)
            self.assertNotIn('PRIVATE_SENTINEL', out.getvalue() + err.getvalue())
            if expected != 2:
                self.assertEqual(len(json.loads(out.getvalue())['items']), 1)
            else:
                self.assertEqual(out.getvalue(), '')
        for argv in ([], ['--all=PRIVATE_SENTINEL'], ['--object-id'], ['--kind', 'paper']):
            err = io.StringIO()
            with redirect_stderr(err), self.assertRaises(SystemExit) as caught:
                Command().run_from_argv(['manage.py', 'registry_audit', *argv])
            self.assertEqual(caught.exception.code, 2)
            self.assertNotIn('PRIVATE_SENTINEL', err.getvalue())
