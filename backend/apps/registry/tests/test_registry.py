import hashlib
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, OperationalError, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from apps.documents.models import Document, DocumentVersion
from apps.experiments.models import ExperimentProject, ExperimentRun
from apps.materials.models import Material, MaterialVersion
from apps.papers.models import Paper
from apps.registry.models import ResearchObject, ResearchObjectBinding, ResearchRevision
from apps.registry import services
from apps.registry.services import RegistryError, check_invariants, plan_registration, register


@override_settings(REGISTRY_BACKFILL_ENABLED=True)
class RegistryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='registry-synthetic')
        self.material = Material.objects.create(title='synthetic', owner=self.user)
        self.mv = MaterialVersion.objects.create(material=self.material, number=1, sha256='a'*64,
            filename='synthetic.md', format='md', storage_key='synthetic-only', size=3, created_by=self.user)
        self.document = Document.objects.create(title='synthetic document')
        self.dv = DocumentVersion.objects.create(document=self.document, version=1, markdown='synthetic v1')
        self.paper = Paper.objects.create(title='synthetic paper', abstract='NEVER COPY', source_pdf_path='NEVER COPY')
        self.project = ExperimentProject.objects.create(title='synthetic project', owner=self.user, protocol_markdown='NEVER COPY')
        self.run = ExperimentRun.objects.create(project=self.project, notes='NEVER COPY', params_json={'secret':'NEVER COPY'})

    def plan(self, kind, pk, **kwargs):
        kwargs.setdefault('actor_id', self.user.pk)
        return plan_registration(kind, pk, **kwargs)

    def submit(self, plan, **changes):
        args = dict(actor_id=plan['actor_id'], operation_key=plan['operation_key'],
                    version_id=plan['version_id'], source_revision_id=plan['source_revision_id'],
                    expected_observation_sha256=plan['observation_sha256'],
                    expected_current_revision_id=plan['expected_current_revision_id'])
        args.update(changes)
        return register(plan['legacy_model'], plan['legacy_pk'], **args)

    def apply(self, kind, row, version=None, **kwargs):
        return self.submit(self.plan(kind, row.pk, version_id=version.pk if version else None, **kwargs))

    def expect_code(self, code, func):
        with self.assertRaises(RegistryError) as caught:
            func()
        self.assertEqual(caught.exception.code, code)

    def test_five_adapters_and_hash_semantics(self):
        for kind, row, version, payload in [
            ('material',self.material,self.mv,'material_version'), ('document',self.document,self.dv,'document_version'),
            ('paper',self.paper,None,'baseline_snapshot'), ('experiment_project',self.project,None,'baseline_snapshot'),
            ('experiment_run',self.run,None,'baseline_snapshot')]:
            with self.subTest(kind=kind):
                result=self.apply(kind,row,version)
                obj=ResearchObject.objects.get(pk=result.object_id); rev=ResearchRevision.objects.get(pk=result.revision_id)
                self.assertEqual(rev.payload_kind,payload); self.assertEqual(check_invariants(obj.pk),[])
                self.assertEqual(obj.policy_origin,'legacy_adapter'); self.assertNotIn('NEVER COPY',str(rev.snapshot))
                if kind in ('paper','document'):
                    self.assertIsNone(obj.owner_id); self.assertEqual(obj.ownership_state,'team_custody')
                else:
                    self.assertEqual(obj.owner_id,self.user.pk)
                if payload=='baseline_snapshot':
                    self.assertEqual(rev.snapshot['schema_version'],'registry-baseline-v1')
                    self.assertIsNone(rev.file_sha256); self.assertEqual(rev.content_sha256,services.digest(rev.snapshot))
                if kind=='material':
                    self.assertEqual(rev.file_sha256,self.mv.sha256); self.assertIsNone(rev.content_sha256)
                if kind=='document':
                    self.assertEqual(rev.content_sha256,hashlib.sha256(self.dv.markdown.encode()).hexdigest()); self.assertIsNone(rev.file_sha256)

    def test_same_key_retry_distinct_entities(self):
        a=self.apply('paper',self.paper); b=self.apply('paper',self.paper)
        self.assertEqual((a.object_id,a.revision_id),(b.object_id,b.revision_id)); self.assertEqual(b.action,'unchanged')
        other=Paper.objects.create(title=self.paper.title,slug='another')
        c=self.apply('paper',other); self.assertNotEqual(a.object_id,c.object_id)
        self.assertEqual(ResearchObjectBinding.objects.count(),2)

    def test_a_b_a_and_conflicting_operation(self):
        a=self.apply('paper',self.paper)
        self.paper.year=2025; self.paper.save()
        old_key=ResearchRevision.objects.get(pk=a.revision_id).operation_key
        self.expect_code('operation_conflict',lambda:self.submit(self.plan('paper',self.paper.pk), operation_key=old_key))
        b=self.apply('paper',self.paper)
        self.paper.year=None; self.paper.save()
        c=self.apply('paper',self.paper)
        self.assertEqual(len({a.revision_id,b.revision_id,c.revision_id}),3)
        self.assertEqual(list(ResearchRevision.objects.order_by('number').values_list('number',flat=True)),[1,2,3])

    def test_dry_run_switch_stop(self):
        self.plan('paper',self.paper.pk)
        for model in (ResearchObject,ResearchRevision,ResearchObjectBinding): self.assertEqual(model.objects.count(),0)
        with override_settings(REGISTRY_BACKFILL_ENABLED=False):
            self.expect_code('backfill_disabled',lambda:self.apply('paper',self.paper))
        self.apply('paper',self.paper)
        with override_settings(REGISTRY_BACKFILL_ENABLED=False):
            self.expect_code('backfill_disabled',lambda:self.apply('paper',self.paper)); self.plan('paper',self.paper.pk)
        for model in (ResearchObject,ResearchRevision,ResearchObjectBinding): self.assertEqual(model.objects.count(),1)
        self.assertEqual(Paper.objects.get(pk=self.paper.pk).abstract,'NEVER COPY')

    def test_stale_and_current_conflict(self):
        plan=self.plan('paper',self.paper.pk)
        self.paper.year=2024; self.paper.save()
        self.expect_code('stale',lambda:self.submit(plan))
        self.assertEqual(ResearchObject.objects.count(),0)
        plan=self.plan('paper',self.paper.pk); result=self.apply('paper',self.paper)
        self.expect_code('current_conflict',lambda:self.submit(plan,operation_key='racer'))
        self.paper.year=2023; self.paper.save()
        self.assertEqual(check_invariants(result.object_id),['stale'])
        self.assertEqual(ResearchObject.objects.get(pk=result.object_id).current_revision_id,result.revision_id)

    def test_mid_transaction_stale_rolls_back(self):
        original=services._observe; calls=0
        def changed(*args,**kwargs):
            nonlocal calls
            calls+=1; result=original(*args,**kwargs)
            return (result[0],result[1],'0'*64) if calls==3 else result
        with patch.object(services,'_observe',side_effect=changed):
            self.expect_code('stale',lambda:self.apply('paper',self.paper))
        for model in (ResearchObject,ResearchRevision,ResearchObjectBinding): self.assertEqual(model.objects.count(),0)

    def test_lock_conflict_is_explicit(self):
        plan=self.plan('paper',self.paper.pk)
        with patch.object(services,'_observe',side_effect=OperationalError('synthetic lock')):
            self.expect_code('concurrent_conflict',lambda:self.submit(plan))
        self.assertEqual(ResearchObject.objects.count(),0)

    def test_fixed_versions_wrong_owner_and_tampering(self):
        first=self.apply('document',self.document,self.dv)
        v2=DocumentVersion.objects.create(document=self.document,version=2,markdown='synthetic v2')
        second=self.apply('document',self.document,v2)
        fixed=self.apply('document',self.document,self.dv)
        self.assertEqual(fixed.revision_id,first.revision_id)
        self.assertEqual(ResearchObject.objects.get(pk=first.object_id).current_revision_id,second.revision_id)
        other=Document.objects.create(title='other')
        self.expect_code('version_ownership_mismatch',lambda:self.apply('document',other,self.dv))
        self.dv.markdown='changed old content'; self.dv.save()
        self.expect_code('fixed_content_changed',lambda:self.apply('document',self.document,self.dv))

    def test_cross_object_current_and_type(self):
        first=self.apply('paper',self.paper); second=self.apply('document',self.document,self.dv)
        ResearchObject.objects.filter(pk=first.object_id).update(current_revision_id=second.revision_id)
        self.assertIn('current_ownership_mismatch',check_invariants(first.object_id))
        self.expect_code('current_ownership_mismatch',lambda:self.apply('paper',self.paper))
        ResearchObject.objects.filter(pk=first.object_id).update(object_type='material',current_revision=None)
        self.assertEqual(check_invariants(first.object_id),['binding_type_mismatch'])
        self.expect_code('binding_type_mismatch',lambda:self.apply('paper',self.paper))

    def test_fixed_delete_cascade_current_source_set_null(self):
        a=self.apply('material',self.material,self.mv)
        b=self.apply('document',self.document,self.dv,source_revision_id=a.revision_id)
        self.mv.delete()
        self.assertFalse(ResearchRevision.objects.filter(pk=a.revision_id).exists())
        self.assertIsNone(ResearchObject.objects.get(pk=a.object_id).current_revision_id)
        self.assertIsNone(ResearchRevision.objects.get(pk=b.revision_id).source_revision_id)
        self.dv.delete()
        self.assertFalse(ResearchRevision.objects.filter(pk=b.revision_id).exists())
        self.assertIsNone(ResearchObject.objects.get(pk=b.object_id).current_revision_id)

    def test_old_entity_delete(self):
        for kind,row,version in [('material',self.material,self.mv),('document',self.document,self.dv),('paper',self.paper,None),('experiment_run',self.run,None),('experiment_project',self.project,None)]:
            with self.subTest(kind=kind):
                result=self.apply(kind,row,version); row.delete()
                self.assertFalse(ResearchObjectBinding.objects.filter(research_object_id=result.object_id).exists())
                self.assertEqual(check_invariants(result.object_id),['source_deleted'])

    def test_snapshot_and_source_cycle_checker(self):
        a=self.apply('paper',self.paper)
        rev=ResearchRevision.objects.get(pk=a.revision_id)
        changed=dict(rev.snapshot, year=1900)
        ResearchRevision.objects.filter(pk=rev.pk).update(snapshot=changed)
        self.assertIn('snapshot_hash_mismatch',check_invariants(a.object_id))
        ResearchRevision.objects.filter(pk=rev.pk).update(snapshot=rev.snapshot,source_revision_id=rev.pk)
        self.assertIn('source_cycle',check_invariants(a.object_id))
        self.expect_code('source_cycle',lambda:self.apply('document',self.document,self.dv,source_revision_id=rev.pk))

    def test_binding_db_constraints(self):
        def obj(kind='material'):
            return ResearchObject.objects.create(object_type=kind,title='synthetic',ownership_state='known',observed_at=timezone.now())
        for fields in ({},{'material':self.material,'paper':self.paper}):
            with self.subTest(fields=list(fields)),self.assertRaises(IntegrityError),transaction.atomic():
                ResearchObjectBinding.objects.create(research_object=obj(),**fields)
        for kind,row in [('material',self.material),('paper',self.paper),('document',self.document),('experiment_project',self.project),('experiment_run',self.run)]:
            ResearchObjectBinding.objects.create(research_object=obj(kind),**{kind:row})
            with self.subTest(kind=kind),self.assertRaises(IntegrityError),transaction.atomic():
                ResearchObjectBinding.objects.create(research_object=obj(kind),**{kind:row})
        with self.assertRaises(IntegrityError),transaction.atomic(): obj('invalid')
        with self.assertRaises(IntegrityError),transaction.atomic():
            ResearchObjectBinding.objects.create(research_object=ResearchObject.objects.first(),material=self.material)

    def test_revision_db_constraints(self):
        a=self.apply('material',self.material,self.mv)
        for update in [{'number':0},{'payload_kind':'baseline_snapshot'},{'snapshot':{}},{'material_version_id':None},{'payload_kind':'other'}]:
            with self.subTest(update=update),self.assertRaises(IntegrityError),transaction.atomic():
                ResearchRevision.objects.filter(pk=a.revision_id).update(**update)
        for kind,row,version in [('material',self.material,self.mv),('document',self.document,self.dv),('paper',self.paper,None)]:
            result=self.apply(kind,row,version); rev=ResearchRevision.objects.get(pk=result.revision_id)
            fields={f.attname:getattr(rev,f.attname) for f in rev._meta.fields if f.name not in ('id','created_at')}
            changes=[{'operation_key':'other'},{'number':2}]
            if kind!='paper': changes.append({'number':2,'operation_key':'other'})
            for change in changes:
                with self.subTest(kind=kind,change=change),self.assertRaises(IntegrityError),transaction.atomic():
                    ResearchRevision.objects.create(**(fields|change))

    def table_state(self):
        return [list(model.objects.order_by('pk').values())
                for model in (ResearchObject, ResearchRevision, ResearchObjectBinding)]

    def check_projection_refresh(self, kind, row, version):
        initial = self.plan(kind, row.pk, version_id=version.pk)
        result = self.submit(initial)
        revision_before = ResearchRevision.objects.filter(pk=result.revision_id).values().get()
        row.title = 'updated projection'
        if kind == 'material':
            row.owner = get_user_model().objects.create_user(username='new-owner')
        row.save()
        self.assertEqual(check_invariants(result.object_id), ['stale'])
        plan = self.plan(kind, row.pk, version_id=version.pk)
        self.assertTrue(plan['operation_key'].startswith('projection:'))
        refreshed = self.submit(plan)
        obj = ResearchObject.objects.get(pk=result.object_id)
        self.assertEqual((refreshed.action, refreshed.revision_id), ('unchanged', result.revision_id))
        self.assertEqual(obj.title, row.title)
        self.assertEqual(obj.owner_id, row.owner_id if kind == 'material' else None)
        self.assertEqual(obj.ownership_state, 'known' if kind == 'material' else 'team_custody')
        self.assertEqual(obj.observation_sha256, plan['observation_sha256'])
        self.assertEqual(check_invariants(obj.pk), [])
        self.assertEqual(ResearchRevision.objects.filter(pk=result.revision_id).values().get(), revision_before)
        self.assertEqual(self.plan(kind, row.pk, version_id=version.pk)['operation_key'], plan['operation_key'])
        self.assertEqual(self.submit(plan), refreshed)
        self.assertEqual(ResearchRevision.objects.count(), 1)
        # Projection keys are recomputable, not new revision receipts.
        self.assertFalse(ResearchRevision.objects.filter(operation_key=plan['operation_key']).exists())
        row.title = 'later projection'
        row.save()
        before = self.table_state()
        self.expect_code('stale', lambda: self.submit(plan))
        later = self.plan(kind, row.pk, version_id=version.pk)
        self.expect_code('operation_conflict', lambda: self.submit(later, operation_key=plan['operation_key']))
        self.assertEqual(self.table_state(), before)

    def test_material_fixed_projection_refresh(self):
        self.check_projection_refresh('material', self.material, self.mv)

    def test_document_fixed_projection_refresh(self):
        self.check_projection_refresh('document', self.document, self.dv)

    def test_persisted_key_observation_metadata_source_actor_conflict(self):
        plan = self.plan('material', self.material.pk, version_id=self.mv.pk)
        self.submit(plan)
        source = self.apply('paper', self.paper)
        actor = get_user_model().objects.create_user(username='different-actor')
        before = self.table_state()
        for changed in ({'expected_observation_sha256': '0'*64},
                        {'actor_id': actor.pk}, {'source_revision_id': source.revision_id}):
            with self.subTest(changed=changed):
                self.expect_code('operation_conflict', lambda: self.submit(plan, **changed))
                self.assertEqual(self.table_state(), before)
        self.material.title = 'different metadata'
        self.material.save()
        updated = self.plan('material', self.material.pk, version_id=self.mv.pk)
        self.expect_code('operation_conflict', lambda: self.submit(updated, operation_key=plan['operation_key']))
        self.assertEqual(self.table_state(), before)

    def test_plan_reuses_current_key_and_rejects_arbitrary_noop_key(self):
        for kind, row, version in [('paper', self.paper, None), ('material', self.material, self.mv)]:
            with self.subTest(kind=kind):
                first = self.plan(kind, row.pk, version_id=version.pk if version else None)
                result = self.submit(first)
                noop = self.plan(kind, row.pk, version_id=version.pk if version else None)
                self.assertEqual(noop['operation_key'], first['operation_key'])
                self.assertEqual(self.submit(noop).revision_id, result.revision_id)
                self.assertEqual(self.submit(first).revision_id, result.revision_id)
                before = self.table_state()
                self.expect_code('operation_conflict', lambda: self.submit(noop, operation_key='arbitrary-new-key'))
                self.assertEqual(self.table_state(), before)
                row.title = 'changed source'
                row.save()
                changed = self.plan(kind, row.pk, version_id=version.pk if version else None)
                self.expect_code('operation_conflict', lambda: self.submit(changed, operation_key='arbitrary-new-key'))
                self.assertEqual(self.table_state(), before)

    def test_source_uuid_string_first_and_retry(self):
        source = self.apply('paper', self.paper)
        for as_string in (True, False):
            with self.subTest(as_string=as_string):
                document = Document.objects.create(title=f'uuid target {as_string}')
                version = DocumentVersion.objects.create(document=document, version=1, markdown='synthetic')
                source_id = str(source.revision_id) if as_string else source.revision_id
                plan = self.plan('document', document.pk, version_id=version.pk, source_revision_id=source_id)
                other = self.plan('document', document.pk, version_id=version.pk, source_revision_id=source.revision_id)
                self.assertEqual(plan, other)
                first = self.submit(plan, source_revision_id=source_id)
                for retry_source in (source.revision_id, str(source.revision_id)):
                    retry = self.submit(plan, source_revision_id=retry_source)
                    self.assertEqual((first.object_id, first.revision_id), (retry.object_id, retry.revision_id))
                    self.assertEqual(retry.action, 'unchanged')

    def test_source_invalid_missing_and_deleted_binding(self):
        for source_id in ('not-a-uuid', uuid.uuid4()):
            self.expect_code('source_revision_unavailable', lambda: self.plan('paper', self.paper.pk, source_revision_id=source_id))
        source = self.apply('paper', self.paper)
        plan = self.plan('document', self.document.pk, version_id=self.dv.pk, source_revision_id=source.revision_id)
        self.paper.delete()
        before = self.table_state()
        self.expect_code('source_revision_unavailable', lambda: self.submit(plan))
        self.assertEqual(self.table_state(), before)

    def test_explicit_human_system_actor_binding_identity_and_delete(self):
        for name in ('human-operator', 'system-backfill'):
            with self.subTest(actor=name):
                actor = get_user_model().objects.create_user(username=name)
                plan = self.plan('experiment_project', self.project.pk, actor_id=actor.pk)
                result = self.submit(plan)
                obj = ResearchObject.objects.get(pk=result.object_id)
                revision = ResearchRevision.objects.get(pk=result.revision_id)
                binding = ResearchObjectBinding.objects.get(research_object=obj)
                self.assertEqual(revision.created_by_id, actor.pk)
                self.assertEqual(obj.created_by_id, actor.pk)
                self.assertNotEqual(obj.created_by_id, self.project.owner_id)
                self.assertIsInstance(binding.pk, uuid.UUID)
                self.assertIsNotNone(binding.created_at)
                before = (binding.pk, binding.created_at, obj.created_by_id, revision.created_by_id)
                self.submit(plan)
                binding.refresh_from_db(); obj.refresh_from_db(); revision.refresh_from_db()
                self.assertEqual((binding.pk, binding.created_at, obj.created_by_id, revision.created_by_id), before)
                actor.delete()
                obj.refresh_from_db(); revision.refresh_from_db()
                self.assertIsNone(obj.created_by_id)
                self.assertIsNone(revision.created_by_id)
                self.assertTrue(ExperimentProject.objects.filter(pk=self.project.pk).exists())
                obj.delete()  # Separate synthetic registration for the second actor.
        self.expect_code('actor_required', lambda: self.plan('paper', self.paper.pk, actor_id=None))
        self.expect_code('actor_unavailable', lambda: self.plan('paper', self.paper.pk, actor_id=999999))

    def test_projection_refresh_cas_and_second_observation_rollback(self):
        first = self.apply('document', self.document, self.dv)
        self.document.title = 'updated'
        self.document.save()
        plan = self.plan('document', self.document.pk, version_id=self.dv.pk)
        before = self.table_state()
        self.expect_code('current_conflict', lambda: self.submit(plan, expected_current_revision_id=None))
        original = services._observe
        calls = 0
        def changed(*args, **kwargs):
            nonlocal calls
            calls += 1
            result = original(*args, **kwargs)
            return (result[0], result[1], '0'*64) if calls == 2 else result
        with patch.object(services, '_observe', side_effect=changed):
            self.expect_code('stale', lambda: self.submit(plan))
        self.assertEqual(self.table_state(), before)
        self.assertEqual(ResearchObject.objects.get(pk=first.object_id).title, 'synthetic document')

    def test_historical_fixed_projection_keeps_current_watermark(self):
        first = self.apply('document', self.document, self.dv)
        v2 = DocumentVersion.objects.create(document=self.document, version=2, markdown='v2')
        second = self.apply('document', self.document, v2)
        self.document.title = 'new title'
        self.document.save()
        replay = self.apply('document', self.document, self.dv)
        obj = ResearchObject.objects.get(pk=first.object_id)
        self.assertEqual(replay.revision_id, first.revision_id)
        self.assertEqual(obj.current_revision_id, second.revision_id)
        self.assertEqual(obj.title, self.document.title)
        self.assertEqual(check_invariants(obj.pk), [])

    def test_plan_key_binds_actor_source_and_versions(self):
        source = self.apply('paper', self.paper)
        actor = get_user_model().objects.create_user(username='other-operator')
        kwargs = dict(version_id=self.dv.pk)
        base = self.plan('document', self.document.pk, **kwargs)
        changed = [self.plan('document', self.document.pk, actor_id=actor.pk, **kwargs),
                   self.plan('document', self.document.pk, source_revision_id=source.revision_id, **kwargs)]
        for constant in ('ADAPTER_VERSION', 'SCHEMA_VERSION', 'CANONICALIZATION_VERSION'):
            with patch.object(services, constant, 'future-version'):
                changed.append(self.plan('document', self.document.pk, **kwargs))
        self.assertEqual(len({p['operation_key'] for p in [base, *changed]}), 6)
        self.assertEqual(ResearchRevision.objects.count(), 1)  # Plans are read-only.

    def check_baseline_actor_noop(self, kind, row, changed_fields):
        first_plan = self.plan(kind, row.pk)
        first = self.submit(first_plan)
        actor_b = get_user_model().objects.create_user(username='actor-b')
        noop = self.plan(kind, row.pk, actor_id=actor_b.pk)
        self.assertEqual(noop['observation_sha256'], first_plan['observation_sha256'])
        before = self.table_state()
        second = self.submit(noop)
        self.assertEqual((second.action, second.revision_id), ('unchanged', first.revision_id))
        self.assertTrue(noop['operation_key'].startswith('noop:'))
        self.assertEqual(self.plan(kind, row.pk, actor_id=actor_b.pk), noop)
        self.assertEqual(self.submit(noop), second)
        self.assertEqual(self.table_state(), before)
        obj = ResearchObject.objects.get(pk=first.object_id)
        self.assertEqual(obj.current_revision_id, first.revision_id)
        self.assertEqual(obj.revisions.count(), 1)
        self.assertEqual(obj.current_revision.created_by_id, self.user.pk)
        self.assertEqual(check_invariants(obj.pk), [])
        self.expect_code('operation_conflict', lambda: self.submit(noop, operation_key='noop:arbitrary'))
        self.expect_code('operation_conflict', lambda: self.submit(first_plan, actor_id=actor_b.pk))
        self.assertEqual(self.table_state(), before)
        for name, value in changed_fields.items():
            setattr(row, name, value)
        row.save()
        self.expect_code('stale', lambda: self.submit(noop))
        changed = self.plan(kind, row.pk, actor_id=actor_b.pk)
        self.expect_code('operation_conflict', lambda: self.submit(changed, operation_key=noop['operation_key']))
        self.assertEqual(self.table_state(), before)
        third = self.submit(changed)
        self.assertEqual(third.action, 'created')
        self.assertNotEqual(third.revision_id, first.revision_id)
        obj.refresh_from_db()
        self.assertEqual(obj.revisions.count(), 2)
        self.assertEqual(obj.current_revision_id, third.revision_id)
        self.assertEqual(obj.current_revision.created_by_id, actor_b.pk)
        self.assertEqual(obj.created_by_id, self.user.pk)
        self.assertEqual(obj.revisions.get(pk=first.revision_id).created_by_id, self.user.pk)
        self.assertEqual(check_invariants(obj.pk), [])

    def test_paper_actor_change_is_noop(self):
        self.check_baseline_actor_noop('paper', self.paper, {'year': 2025})

    def test_project_actor_change_is_noop(self):
        self.check_baseline_actor_noop('experiment_project', self.project, {'title': 'changed project'})

    def test_run_actor_change_is_noop(self):
        self.check_baseline_actor_noop('experiment_run', self.run, {'finished_at': timezone.now()})

    def test_context_lock_order_and_read_only_query(self):
        from django.db.models.query import QuerySet
        result = self.apply('paper', self.paper)
        original = QuerySet.select_for_update
        calls = []

        def record(queryset, *args, **kwargs):
            calls.append((queryset.model, args, kwargs))
            return original(queryset, *args, **kwargs)

        # Call-order spy only; SQLite does not prove PostgreSQL lock behavior.
        with patch.object(QuerySet, 'select_for_update', autospec=True, side_effect=record):
            obj = services._context('paper', self.paper.pk, lock=True)
            self.assertEqual(obj.pk, result.object_id)
            self.assertEqual(calls, [
                (ResearchObjectBinding, (), {'nowait': True}),
                (ResearchObject, (), {'nowait': True}),
            ])
            calls.clear()
            obj = services._context('paper', self.paper.pk, lock=False)
            self.assertEqual(obj.pk, result.object_id)
            self.assertEqual(calls, [])

    def test_old_plan_after_binding_delete_is_current_conflict(self):
        result = self.apply('paper', self.paper)
        plan = self.plan('paper', self.paper.pk)
        ResearchObjectBinding.objects.get(research_object_id=result.object_id).delete()
        before = self.table_state()
        self.expect_code('current_conflict', lambda: self.submit(plan))
        self.assertEqual(self.table_state(), before)
        obj = ResearchObject.objects.get(pk=result.object_id)
        self.assertEqual(obj.current_revision_id, result.revision_id)
        self.assertFalse(ResearchObjectBinding.objects.filter(paper=self.paper).exists())


class InitialMigrationTests(TransactionTestCase):
    def test_initial_operations_on_legacy_schema(self):
        from django.apps import apps
        from django.db.migrations.state import ProjectState
        from importlib import import_module
        migration = import_module('apps.registry.migrations.0001_initial').Migration('0001_initial', 'registry')
        state = ProjectState.from_apps(apps)
        for name in ('researchobjectbinding', 'researchrevision', 'researchobject'):
            state.remove_model('registry', name)
        with connection.constraint_checks_disabled():
            with connection.schema_editor() as editor:
                editor.remove_field(ResearchObject, ResearchObject._meta.get_field('current_revision'))
            with connection.cursor() as cursor:
                for name in ('researchobjectbinding', 'researchrevision', 'researchobject'):
                    cursor.execute('DROP TABLE registry_' + name)
            with connection.schema_editor() as editor:
                for operation in migration.operations:
                    before = state.clone()
                    operation.state_forwards('registry', state)
                    operation.database_forwards('registry', editor, before, state)
        self.assertEqual(len([t for t in connection.introspection.table_names() if t.startswith('registry_')]), 3)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ResearchObject.objects.create(object_type='invalid', title='synthetic', ownership_state='known', observed_at=timezone.now())
