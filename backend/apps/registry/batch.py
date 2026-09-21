"""有界计划、只读审计与内部原子登记；不修复或重建历史时点。"""
import re
from uuid import UUID
from datetime import timezone as datetime_timezone

from django.contrib.auth import get_user_model
from django.conf import settings
from django.db import connection, transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.documents.models import DocumentVersion
from apps.materials.models import MaterialVersion
from . import services
from .models import ResearchObject

# 编排协议的代码版本标识，不冒充 Git 提交或生产发布版本。
CODE_VERSION = 'registry-plan-2'
MAX_PK = 2**63 - 1
PLAN_FIELDS = (
    'legacy_model', 'legacy_pk', 'version_id', 'actor_id', 'source_revision_id',
    'observation_sha256', 'expected_current_revision_id', 'research_object_id', 'operation_key',
)
REJECTION_CODES = frozenset({
    'source_deleted', 'fixed_version_required', 'version_ownership_mismatch',
    'invalid_file_hash', 'snapshot_too_large', 'binding_type_mismatch',
    'current_ownership_mismatch', 'actor_unavailable', 'source_revision_unavailable', 'source_cycle',
})


class PlanError(ValueError):
    """命令仅输出此稳定原因码，不输出底层异常。"""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _target_fingerprint():
    # 仅用于误投目标保护，不是数据库身份认证或 manifest 签名。
    # 白名单排除 USER/PASSWORD/OPTIONS；原始连接值不得进入 manifest。
    config = connection.settings_dict
    return services.digest({'vendor': connection.vendor, **{
        key.lower(): str(config.get(key) or '') for key in ('ENGINE', 'HOST', 'PORT', 'NAME')
    }})


def _integer(value, code, *, minimum=0, maximum=MAX_PK):
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,19}', value):
        value = int(value)
    if type(value) is not int or not minimum <= value <= maximum:
        raise PlanError(code)
    return value


def _cutoff(value):
    if value is None:
        return timezone.now().astimezone(datetime_timezone.utc)
    if not isinstance(value, str) or len(value) > 64:
        raise PlanError('invalid_cutoff')
    try:
        parsed = parse_datetime(value)
        if parsed is None or timezone.is_naive(parsed):
            raise ValueError
        return parsed.astimezone(datetime_timezone.utc)
    except (ValueError, OverflowError):
        raise PlanError('invalid_cutoff') from None


def _plan_batch(kind, actor_id, after_pk, through_pk, limit, cutoff):
    if not isinstance(kind, str) or kind not in services.MODELS:
        raise PlanError('invalid_kind')
    actor_id = _integer(actor_id, 'invalid_actor', minimum=1)
    after_pk = _integer(after_pk, 'invalid_range')
    limit = _integer(limit, 'invalid_limit', minimum=1, maximum=50)
    if through_pk is not None:
        through_pk = _integer(through_pk, 'invalid_range')
        if through_pk < after_pk:
            raise PlanError('invalid_range')
    cutoff = _cutoff(cutoff)
    if not get_user_model().objects.filter(pk=actor_id).exists():
        raise PlanError('actor_unavailable')
    source = services.MODELS[kind].objects
    if through_pk is None:
        through_pk = source.aggregate(upper=Max('pk'))['upper'] or 0
    if through_pk < after_pk:
        raise PlanError('invalid_range')
    scope = {'kind': kind, 'actor_id': actor_id, 'after_pk': after_pk,
             'through_pk': through_pk, 'limit': limit,
             'cutoff': cutoff.isoformat(timespec='microseconds').replace('+00:00', 'Z')}
    query = source.filter(pk__gt=after_pk, pk__lte=through_pk)
    if kind not in ('material', 'document'):
        query = query.filter(updated_at__lte=cutoff)
    # 仅多取一个 PK 判断 has_more，正文/快照只由单项服务按既有契约处理。
    candidates = list(query.order_by('pk').values_list('pk', flat=True)[:limit + 1])
    items = []
    for pk in candidates[:limit]:
        version_id = None
        if kind in ('material', 'document'):
            model, number = (MaterialVersion, 'number') if kind == 'material' else (DocumentVersion, 'version')
            version_id = model.objects.filter(**{f'{kind}_id': pk}, created_at__lte=cutoff).order_by(
                '-' + number, '-pk').values_list('pk', flat=True).first()
        item = dict.fromkeys(PLAN_FIELDS)
        item.update(legacy_model=kind, legacy_pk=pk, version_id=version_id, actor_id=actor_id)
        try:
            if kind in ('material', 'document') and version_id is None:
                raise services.RegistryError('fixed_version_required')
            plan = services.plan_registration(kind, pk, actor_id=actor_id,
                                              version_id=version_id, source_revision_id=None)
            item = {key: plan[key] for key in PLAN_FIELDS}
            item.update(status='planned', reason=None)
        except services.RegistryError as error:
            if error.code not in REJECTION_CODES:
                raise PlanError('unexpected_error') from None
            item.update(status='rejected', reason=error.code)
        items.append(item)
    planned = sum(item['status'] == 'planned' for item in items)
    manifest = {
        'schema_version': 'registry-plan-v2', 'mode': 'dry-run', 'code_version': CODE_VERSION,
        'target_fingerprint': _target_fingerprint(),
        'adapter_version': services.ADAPTER_VERSION, 'revision_schema_version': services.SCHEMA_VERSION,
        'canonicalization_version': services.CANONICALIZATION_VERSION,
        'scope': scope, 'baseline_digest': services.digest(items), 'items': items,
        'summary': {'scanned': len(items), 'planned': planned,
                    'rejected': len(items) - planned, 'created': 0},
        'scan_cursor': items[-1]['legacy_pk'] if items else after_pk,
        'has_more': len(candidates) > limit,
    }
    manifest['batch_id'] = services.digest(manifest)
    return manifest


def plan_batch(*, kind, actor_id, after_pk=0, through_pk=None, limit=20, cutoff=None):
    """冻结 cutoff/through 后生成一页；续页必须沿用返回的冻结范围。

    cutoff 只限定扫描资格，不代表完整历史快照或并发一致的数据库快照。
    registry: key 也可能是已有登记的 receipt，不能据此前缀推测创建数量。
    """
    try:
        return _plan_batch(kind, actor_id, after_pk, through_pk, limit, cutoff)
    except PlanError:
        raise
    except Exception:
        raise PlanError('unexpected_error') from None


AUDIT_CODE_VERSION = 'registry-audit-1'
AUDIT_REASON_CODES = REJECTION_CODES | frozenset({
    'snapshot_schema_mismatch', 'snapshot_hash_mismatch', 'fixed_content_changed',
    'stale', 'invalid_legacy_identity', 'baseline_has_no_legacy_version',
})


class AuditError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _audit_objects(object_ids):
    if not isinstance(object_ids, (list, tuple)) or not 1 <= len(object_ids) <= 50:
        raise AuditError('invalid_object_ids')
    normalized = []
    for value in object_ids:
        if not isinstance(value, str) or len(value) > 45:
            raise AuditError('invalid_object_id')
        try:
            normalized.append(str(UUID(value)))
        except ValueError:
            raise AuditError('invalid_object_id') from None
    if len(set(normalized)) != len(normalized):
        raise AuditError('duplicate_object_id')

    items = []
    summary = dict(requested=len(normalized), checked=0, ok=0, with_findings=0, unavailable=0, writes=0)
    for object_id in sorted(normalized):
        try:
            reasons = services.check_invariants(object_id)
        except ResearchObject.DoesNotExist:
            reasons = ['object_unavailable']
            status = 'unavailable'
            summary['unavailable'] += 1
        else:
            if not isinstance(reasons, list) or any(
                    not isinstance(reason, str) or reason not in AUDIT_REASON_CODES for reason in reasons):
                raise AuditError('unexpected_error')
            reasons = sorted(set(reasons))
            status = 'finding' if reasons else 'ok'
            summary['checked'] += 1
            summary['with_findings' if reasons else 'ok'] += 1
        items.append(dict(object_id=object_id, status=status, reasons=reasons))
    manifest = dict(schema_version='registry-audit-v1', mode='audit',
                    code_version=AUDIT_CODE_VERSION, items=items, summary=summary)
    manifest['batch_id'] = services.digest(manifest)
    return manifest


def audit_objects(object_ids):
    """仅检查显式对象；requested=checked+unavailable，checked=ok+with_findings。"""
    try:
        return _audit_objects(object_ids)
    except AuditError:
        raise
    except Exception:
        raise AuditError('unexpected_error') from None


class ApplyError(ValueError):
    """执行前拒绝的稳定原因；尚未尝试任何登记。"""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _require(condition):
    if not condition:
        raise ApplyError('invalid_manifest')


def _int_in(value, minimum=0, maximum=MAX_PK):
    return type(value) is int and minimum <= value <= maximum


def _hash(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _uuid_or_none(value):
    if value is None:
        return True
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False


def _validate_apply(manifest):
    _require(type(manifest) is dict and set(manifest) == {
        'schema_version', 'mode', 'code_version', 'target_fingerprint', 'adapter_version',
        'revision_schema_version', 'canonicalization_version', 'scope', 'baseline_digest',
        'items', 'summary', 'scan_cursor', 'has_more', 'batch_id'})
    for key, value in {'schema_version': 'registry-plan-v2', 'mode': 'dry-run',
                       'code_version': CODE_VERSION, 'adapter_version': services.ADAPTER_VERSION,
                       'revision_schema_version': services.SCHEMA_VERSION,
                       'canonicalization_version': services.CANONICALIZATION_VERSION}.items():
        _require(manifest[key] == value)
    for key in ('target_fingerprint', 'baseline_digest', 'batch_id'):
        _require(_hash(manifest[key]))
    _require(manifest['batch_id'] == services.digest({k: v for k, v in manifest.items() if k != 'batch_id'}))
    scope, items, summary = manifest['scope'], manifest['items'], manifest['summary']
    _require(type(scope) is dict and set(scope) == {'kind', 'actor_id', 'after_pk', 'through_pk', 'limit', 'cutoff'})
    _require(isinstance(scope['kind'], str) and scope['kind'] in services.MODELS)
    _require(_int_in(scope['actor_id'], 1) and _int_in(scope['after_pk'])
             and _int_in(scope['through_pk']) and scope['through_pk'] >= scope['after_pk']
             and _int_in(scope['limit'], 1, 50))
    _require(isinstance(scope['cutoff'], str) and _cutoff(scope['cutoff']).isoformat(
        timespec='microseconds').replace('+00:00', 'Z') == scope['cutoff'])
    _require(type(items) is list and 1 <= len(items) <= scope['limit'])
    _require(manifest['baseline_digest'] == services.digest(items))
    _require(type(summary) is dict and set(summary) == {'scanned', 'planned', 'rejected', 'created'})
    _require(all(_int_in(value, 0, 50) for value in summary.values()))
    _require(summary == dict(scanned=len(items), planned=len(items), rejected=0, created=0))
    previous = scope['after_pk']
    for item in items:
        _require(type(item) is dict and set(item) == {*PLAN_FIELDS, 'status', 'reason'})
        _require(item['legacy_model'] == scope['kind'] and _int_in(item['actor_id'], 1)
                 and item['actor_id'] == scope['actor_id'])
        _require(_int_in(item['legacy_pk'], previous + 1, scope['through_pk']))
        previous = item['legacy_pk']
        _require(item['status'] == 'planned' and item['reason'] is None)
        # 当前批计划不提供来源选择；不得通过手改 manifest 扩大登记语义。
        _require(item['source_revision_id'] is None)
        _require(_int_in(item['version_id'], 1) if scope['kind'] in ('material', 'document')
                 else item['version_id'] is None)
        _require(_hash(item['observation_sha256']))
        _require(_uuid_or_none(item['research_object_id']) and _uuid_or_none(item['expected_current_revision_id']))
        _require(item['expected_current_revision_id'] is None or item['research_object_id'] is not None)
        _require(isinstance(item['operation_key'], str) and re.fullmatch(
            r'(registry|noop|projection):[0-9a-f]{64}', item['operation_key']) is not None)
    _require(_int_in(manifest['scan_cursor'], 1) and manifest['scan_cursor'] == previous)
    _require(type(manifest['has_more']) is bool)
    _require(not manifest['has_more'] or (len(items) == scope['limit'] and previous < scope['through_pk']))
    if manifest['target_fingerprint'] != _target_fingerprint():
        raise ApplyError('target_mismatch')


APPLY_REASON_CODES = REJECTION_CODES | frozenset({
    'backfill_disabled', 'stale', 'current_conflict', 'operation_conflict',
    'source_revision_conflict', 'fixed_content_changed', 'concurrent_conflict',
    'object_conflict',
})


def apply_batch(manifest):
    """内部入口：预检拒绝抛 ApplyError；单项失败回滚，提交阶段异常报未知。

    必须独占最外层事务；哈希用于完整性/误投检查，不是授权签名。
    同一清单重放委托单项服务校验 receipt，不重新生成计划或猜测版本。
    """
    if getattr(settings, 'REGISTRY_BACKFILL_ENABLED', False) is not True:
        raise ApplyError('backfill_disabled')
    try:
        _validate_apply(manifest)
    except ApplyError:
        raise
    except Exception:
        raise ApplyError('invalid_manifest') from None
    if connection.in_atomic_block or not connection.get_autocommit():
        raise ApplyError('outer_transaction_required')
    results = []
    failed_index = None
    committing = False
    try:
        with transaction.atomic(durable=True):
            for index, item in enumerate(manifest['items']):
                failed_index = index
                if item['research_object_id'] is not None:
                    obj = services._context(item['legacy_model'], item['legacy_pk'], lock=True)
                    if obj is None or str(obj.pk) != item['research_object_id']:
                        raise services.RegistryError('object_conflict')
                result = services.register(item['legacy_model'], item['legacy_pk'],
                    actor_id=item['actor_id'], version_id=item['version_id'],
                    source_revision_id=item['source_revision_id'], operation_key=item['operation_key'],
                    expected_observation_sha256=item['observation_sha256'],
                    expected_current_revision_id=item['expected_current_revision_id'])
                if result.action not in ('created', 'unchanged'):
                    raise RuntimeError
                results.append(dict(legacy_pk=item['legacy_pk'], status=result.action,
                                    object_id=str(result.object_id), revision_id=str(result.revision_id)))
            # 网络中断可能发生在提交已生效之后，不能把退出异常当作确定回滚。
            failed_index = None
            committing = True
    except Exception as error:
        if committing:
            return dict(schema_version='registry-apply-v1', batch_id=manifest['batch_id'],
                        status='commit_unknown', reason='commit_unknown', committed_cursor=None,
                        items=[dict(legacy_pk=item['legacy_pk'], status='commit_unknown')
                               for item in manifest['items']], summary=dict(created=0, unchanged=0))
        reason = error.code if isinstance(error, services.RegistryError) and error.code in APPLY_REASON_CODES else 'unexpected_error'
        items = [dict(legacy_pk=item['legacy_pk'],
                      status='rolled_back' if i < len(results) else ('failed' if i == failed_index else 'not_attempted'),
                      reason=reason if i == failed_index else None)
                 for i, item in enumerate(manifest['items'])]
        return dict(schema_version='registry-apply-v1', batch_id=manifest['batch_id'],
                    status='rolled_back', reason=reason, committed_cursor=None, items=items,
                    summary=dict(created=0, unchanged=0))
    # 此处已离开最外层事务，才可报告 committed 和最终身份。
    return dict(schema_version='registry-apply-v1', batch_id=manifest['batch_id'],
                status='committed', reason=None, committed_cursor=manifest['scan_cursor'], items=results,
                summary=dict(created=sum(i['status'] == 'created' for i in results),
                             unchanged=sum(i['status'] == 'unchanged' for i in results)))
