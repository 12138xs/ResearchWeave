"""内部旁路服务：不提供读取授权、API、后台任务或业务双写。"""
import hashlib
import json
import re
import uuid
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Max
from django.utils import timezone

from apps.documents.models import Document, DocumentVersion
from apps.experiments.models import ExperimentProject, ExperimentRun
from apps.materials.models import Material, MaterialVersion
from apps.papers.models import Paper
from .models import BINDING_FIELDS, ResearchObject, ResearchObjectBinding, ResearchRevision

MODELS = {'material': Material, 'paper': Paper, 'document': Document,
          'experiment_project': ExperimentProject, 'experiment_run': ExperimentRun}
# Only small scalar metadata. Never copy abstract/body/notes/JSON configs/paths.
SNAPSHOT_FIELDS = {
    'paper': ('title', 'year', 'publication_type', 'doi', 'arxiv_id', 'status'),
    'experiment_project': ('title', 'status'),
    'experiment_run': ('status', 'started_at', 'finished_at'),
}


class RegistryError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def text_digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _snapshot(kind, row):
    result = {'schema_version': 'registry-baseline-v1'}
    for key in SNAPSHOT_FIELDS[kind]:
        value = getattr(row, key)
        result[key] = value.isoformat() if hasattr(value, 'isoformat') else value
    if len(canonical(result).encode('utf-8')) > 4096:
        raise RegistryError('snapshot_too_large')
    return result


def _observe(kind, pk, version_id, *, lock=False):
    if kind not in MODELS or not isinstance(pk, int) or isinstance(pk, bool) or pk <= 0:
        raise RegistryError('invalid_legacy_identity')
    qs = MODELS[kind].objects
    if lock:
        qs = qs.select_for_update(nowait=True)
    try:
        row = qs.get(pk=pk)
    except ObjectDoesNotExist:
        raise RegistryError('source_deleted') from None
    owner_id = getattr(row, 'owner_id', None)
    if kind == 'experiment_run':
        parents = ExperimentProject.objects
        if lock:
            parents = parents.select_for_update(nowait=True)
        owner_id = parents.get(pk=row.project_id).owner_id
    custody = kind in ('paper', 'document')
    owner_id = None if custody else owner_id
    title = getattr(row, 'title', f'Run {pk}')
    metadata = {'object_type': kind, 'title': title, 'owner_id': owner_id,
                'ownership_state': 'team_custody' if custody else ('known' if owner_id else 'unresolved'),
                'policy_origin': 'legacy_adapter'}
    payload = {'material_version_id': None, 'document_version_id': None, 'snapshot': None,
               'file_sha256': None, 'content_sha256': None}
    if kind in ('material', 'document'):
        if not isinstance(version_id, int) or isinstance(version_id, bool) or version_id <= 0:
            raise RegistryError('fixed_version_required')
        cls = MaterialVersion if kind == 'material' else DocumentVersion
        versions = cls.objects.select_for_update(nowait=True) if lock else cls.objects
        version = versions.filter(pk=version_id, **{f'{kind}_id': pk}).first()
        if version is None:
            raise RegistryError('version_ownership_mismatch')
        payload['payload_kind'] = f'{kind}_version'
        payload[f'{kind}_version_id'] = version.pk
        if kind == 'material':
            if not re.fullmatch('[0-9a-f]{64}', version.sha256):
                raise RegistryError('invalid_file_hash')
            payload['file_sha256'] = version.sha256  # declared only; never read blob
            metadata.update(format=version.format, size=version.size, version_number=version.number)
            payload['source_kind'] = row.source_kind
        else:
            payload['content_sha256'] = text_digest(version.markdown)
            metadata['version_number'] = version.version
            payload['source_kind'] = 'human_record'
    else:
        if version_id is not None:
            raise RegistryError('baseline_has_no_legacy_version')
        payload.update(payload_kind='baseline_snapshot', snapshot=_snapshot(kind, row),
                       source_kind='paper_metadata' if kind == 'paper' else 'experiment_record')
        # Content hash covers canonical snapshot JSON, never file bytes.
        payload['content_sha256'] = digest(payload['snapshot'])
    payload['metadata_sha256'] = digest(metadata)
    observation = digest({'metadata': metadata, 'payload': payload})
    return metadata, payload, observation


ADAPTER_VERSION = '1'
SCHEMA_VERSION = 'registry-v1'
CANONICALIZATION_VERSION = 'json-sorted-utf8-v1'


def _actor(actor_id):
    # Explicit registering principal, never inferred from the legacy owner/author.
    if not isinstance(actor_id, int) or isinstance(actor_id, bool):
        raise RegistryError('actor_required')
    if not get_user_model().objects.filter(pk=actor_id).exists():
        raise RegistryError('actor_unavailable')
    return actor_id


def _source(source_revision_id):
    if source_revision_id is None:
        return None
    try:
        source_id = uuid.UUID(str(source_revision_id))
    except (ValueError, TypeError, AttributeError):
        raise RegistryError('source_revision_unavailable') from None
    source = ResearchRevision.objects.filter(pk=source_id).first()
    if source is None:
        raise RegistryError('source_revision_unavailable')
    seen = set()
    while source:
        if source.pk in seen:
            raise RegistryError('source_cycle')
        seen.add(source.pk)
        if not ResearchObjectBinding.objects.filter(research_object_id=source.research_object_id).exists():
            raise RegistryError('source_revision_unavailable')
        source = source.source_revision
    return source_id


def _context(kind, pk, *, lock=False):
    bindings = ResearchObjectBinding.objects.select_for_update(nowait=True) if lock else ResearchObjectBinding.objects
    binding = bindings.filter(**{f'{kind}_id': pk}).first()
    if not binding:
        return None
    objects = ResearchObject.objects.select_for_update(nowait=True) if lock else ResearchObject.objects
    obj = objects.get(pk=binding.research_object_id)
    if obj.object_type != kind:
        raise RegistryError('binding_type_mismatch')
    if obj.current_revision_id and obj.current_revision.research_object_id != obj.pk:
        raise RegistryError('current_ownership_mismatch')
    return obj


def _state_matches(revision, payload, observation, source_id):
    """创建操作者是审计信息，不属于科研状态。"""
    return (_same_revision(revision, payload)
            and revision.observation_sha256 == observation
            and revision.metadata_sha256 == payload['metadata_sha256']
            and revision.source_revision_id == source_id
            and revision.generator_kind == 'system'
            and revision.generator_name == 'registry_adapter'
            and revision.generator_version == ADAPTER_VERSION
            and revision.schema_version == SCHEMA_VERSION
            and revision.canonicalization_version == CANONICALIZATION_VERSION)


def _operation_matches(revision, payload, observation, source_id, actor_id):
    return (_state_matches(revision, payload, observation, source_id)
            and revision.created_by_id == actor_id)


def _operation_key(kind, pk, version_id, observation, current_id, source_id, actor_id, *, prefix='registry'):
    return prefix + ':' + digest({
        'kind': kind, 'legacy_pk': pk, 'version_id': version_id,
        'observation_sha256': observation,
        'expected_current_revision_id': str(current_id) if current_id else None,
        'source_revision_id': str(source_id) if source_id else None,
        'actor_id': actor_id, 'adapter_version': ADAPTER_VERSION,
        'schema_version': SCHEMA_VERSION,
        'canonicalization_version': CANONICALIZATION_VERSION,
    })


def _planned_key(kind, pk, version_id, payload, observation, obj, source_id, actor_id):
    if obj and obj.current_revision_id and _state_matches(
            obj.current_revision, payload, observation, source_id):
        if obj.current_revision.created_by_id == actor_id:
            return obj.current_revision.operation_key
        return _operation_key(kind, pk, version_id, observation, obj.current_revision_id,
                              source_id, actor_id, prefix='noop')
    projection = bool(obj and kind in ('material', 'document') and
                      obj.revisions.filter(**{f'{kind}_version_id': version_id}).exists())
    return _operation_key(kind, pk, version_id, observation,
                          obj.current_revision_id if obj else None, source_id, actor_id,
                          prefix='projection' if projection else 'registry')


def plan_registration(kind, pk, *, actor_id, version_id=None, source_revision_id=None):
    """只读预演，返回绑定规范输入的 key；不生成身份 UUID 或持久化报告。"""
    actor_id = _actor(actor_id)
    source_id = _source(source_revision_id)
    _, payload, observation = _observe(kind, pk, version_id)
    obj = _context(kind, pk)
    return {'legacy_model': kind, 'legacy_pk': pk, 'version_id': version_id,
            'actor_id': actor_id, 'source_revision_id': str(source_id) if source_id else None,
            'observation_sha256': observation,
            'expected_current_revision_id': str(obj.current_revision_id) if obj and obj.current_revision_id else None,
            'research_object_id': str(obj.pk) if obj else None,
            'operation_key': _planned_key(kind, pk, version_id, payload, observation, obj, source_id, actor_id)}


@dataclass(frozen=True)
class RegistrationResult:
    action: str
    object_id: object
    revision_id: object


def _same_revision(revision, payload):
    # Mutable object metadata does not rewrite an already fixed old version.
    for key in ('payload_kind', 'material_version_id', 'document_version_id', 'snapshot',
                'file_sha256', 'content_sha256', 'source_kind'):
        if getattr(revision, key) != payload[key]:
            return False
    return True


def _refresh_projection(obj, metadata, kind, pk, version_id, observation):
    """固定历史版本的重读不能倒退 current；水位始终对应 current 的观察。"""
    watermark = observation
    current = obj.current_revision
    current_version = (current.material_version_id or current.document_version_id) if current else None
    if current and current_version != version_id:
        _, _, watermark = _observe(kind, pk, current_version)
    if _observe(kind, pk, version_id)[2] != observation:
        raise RegistryError('stale')
    if current and current_version != version_id and _observe(kind, pk, current_version)[2] != watermark:
        raise RegistryError('stale')
    obj.title = metadata['title']
    obj.owner_id = metadata['owner_id']
    obj.ownership_state = metadata['ownership_state']
    obj.observed_at = timezone.now()
    obj.observation_sha256 = watermark
    obj.save(update_fields=['title', 'owner', 'ownership_state', 'current_revision',
                            'observed_at', 'observation_sha256'])


def register(kind, pk, *, actor_id, operation_key, expected_observation_sha256,
             expected_current_revision_id, version_id=None, source_revision_id=None):
    """验证 plan 的 key，并发/漂移显式失败。

    已存 revision key 必须匹配其观察、元数据、来源和 actor；完全相同的
    current 输入复用此 key。仅 actor 改变时使用可重算的 noop key，返回原
    current 且不改其创建审计。固定版本投影刷新使用可重算的 projection key，
    不改写 revision、不保存额外操作记录；旧输入漂移为 stale，新输入复用旧
    noop/projection key 为 operation_conflict，禁止任意 key 成功但不留痕。
    """
    if not settings.REGISTRY_BACKFILL_ENABLED:
        raise RegistryError('backfill_disabled')
    if not isinstance(operation_key, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}', operation_key):
        raise RegistryError('invalid_operation_key')
    if not isinstance(expected_observation_sha256, str) or not re.fullmatch('[0-9a-f]{64}', expected_observation_sha256):
        raise RegistryError('observation_required')
    actor_id = _actor(actor_id)
    source_id = _source(source_revision_id)
    try:
        with transaction.atomic():
            metadata, payload, observation = _observe(kind, pk, version_id, lock=True)
            obj = _context(kind, pk, lock=True)
            previous = obj.revisions.filter(operation_key=operation_key).first() if obj else None
            if previous and not _operation_matches(
                    previous, payload, expected_observation_sha256, source_id, actor_id):
                raise RegistryError('operation_conflict')
            if observation != expected_observation_sha256:
                raise RegistryError('stale')
            if previous:
                # Exact persisted retries do not rewind current, even after later registrations.
                if previous.pk == obj.current_revision_id or kind in ('material', 'document'):
                    _refresh_projection(obj, metadata, kind, pk, version_id, observation)
                elif _observe(kind, pk, version_id)[2] != observation:
                    raise RegistryError('stale')
                return RegistrationResult('unchanged', obj.pk, previous.pk)
            current_id = str(obj.current_revision_id) if obj and obj.current_revision_id else None
            if current_id != (str(expected_current_revision_id) if expected_current_revision_id else None):
                raise RegistryError('current_conflict')
            if operation_key != _planned_key(kind, pk, version_id, payload, observation, obj, source_id, actor_id):
                raise RegistryError('operation_conflict')
            if obj and obj.current_revision_id and _state_matches(
                    obj.current_revision, payload, observation, source_id):
                if _observe(kind, pk, version_id)[2] != observation:
                    raise RegistryError('stale')
                return RegistrationResult('unchanged', obj.pk, obj.current_revision_id)
            fixed = None
            if obj and kind in ('material', 'document'):
                fixed = obj.revisions.filter(**{f'{kind}_version_id': version_id}).first()
            if fixed:
                if fixed.source_revision_id != source_id:
                    raise RegistryError('source_revision_conflict')
                if not _same_revision(fixed, payload):
                    raise RegistryError('fixed_content_changed')
                _refresh_projection(obj, metadata, kind, pk, version_id, observation)
                return RegistrationResult('unchanged', obj.pk, fixed.pk)
            now = timezone.now()
            if obj is None:
                obj = ResearchObject.objects.create(
                    **{k: metadata[k] for k in ('object_type', 'title', 'owner_id', 'ownership_state', 'policy_origin')},
                    created_by_id=actor_id, observed_at=now, observation_sha256=observation)
                ResearchObjectBinding.objects.create(research_object=obj, **{f'{kind}_id': pk})
            number = (obj.revisions.aggregate(n=Max('number'))['n'] or 0) + 1
            revision = ResearchRevision.objects.create(
                research_object=obj, number=number, operation_key=operation_key,
                observed_at=now, observation_sha256=observation, created_by_id=actor_id,
                source_revision_id=source_id, generator_version=ADAPTER_VERSION,
                schema_version=SCHEMA_VERSION, canonicalization_version=CANONICALIZATION_VERSION,
                **payload)
            obj.current_revision = revision
            _refresh_projection(obj, metadata, kind, pk, version_id, observation)
            return RegistrationResult('created', obj.pk, revision.pk)
    except (IntegrityError, OperationalError):
        raise RegistryError('concurrent_conflict') from None


def check_invariants(object_id):
    """可重复只读检查，返回原因码；不修复、不返回正文或快照。"""
    obj = ResearchObject.objects.get(pk=object_id)
    issues = []
    binding = ResearchObjectBinding.objects.filter(research_object=obj).first()
    if not binding:
        return ['source_deleted']
    populated = [name for name in BINDING_FIELDS if getattr(binding, name) is not None]
    if populated != [f'{obj.object_type}_id']:
        return ['binding_type_mismatch']
    pk = getattr(binding, populated[0])
    if obj.current_revision_id and not obj.revisions.filter(pk=obj.current_revision_id).exists():
        issues.append('current_ownership_mismatch')
    for revision in obj.revisions.all():
        version_id = revision.material_version_id or revision.document_version_id
        try:
            _, payload, observation = _observe(obj.object_type, pk, version_id)
            if revision.payload_kind == 'baseline_snapshot':
                if not isinstance(revision.snapshot, dict) or revision.snapshot.get('schema_version') != 'registry-baseline-v1' or set(revision.snapshot) != {'schema_version', *SNAPSHOT_FIELDS[obj.object_type]}:
                    issues.append('snapshot_schema_mismatch')
                elif digest(revision.snapshot) != revision.content_sha256:
                    issues.append('snapshot_hash_mismatch')
            elif not _same_revision(revision, payload):
                issues.append('fixed_content_changed')
            if revision.pk == obj.current_revision_id and observation != obj.observation_sha256:
                issues.append('stale')
        except RegistryError as exc:
            issues.append(exc.code)
        seen = {revision.pk}
        source = revision.source_revision
        while source:
            if source.pk in seen:
                issues.append('source_cycle')
                break
            seen.add(source.pk)
            source = source.source_revision
    return sorted(set(issues))
