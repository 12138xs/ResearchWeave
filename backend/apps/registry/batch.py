"""有界只读计划与显式对象审计；不执行登记、修复或历史时点重建。"""
import re
from uuid import UUID
from datetime import timezone as datetime_timezone

from django.contrib.auth import get_user_model
from django.db.models import Max
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.documents.models import DocumentVersion
from apps.materials.models import MaterialVersion
from . import services
from .models import ResearchObject

# 编排协议的代码版本标识，不冒充 Git 提交或生产发布版本。
CODE_VERSION = 'registry-plan-1'
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
        'schema_version': 'registry-plan-v1', 'mode': 'dry-run', 'code_version': CODE_VERSION,
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
