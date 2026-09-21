"""单个固定版本的只读质量观察；不作为消费或外发授权。"""
from django.db.models import BooleanField, Count, Exists, F, Func, IntegerField, OuterRef, Q, TextField, Value
from django.db.models.functions import Length
from django.db.models.lookups import GreaterThan
from django.http import Http404

from apps.materials import selectors
from apps.materials.models import MaterialVersion, StructureIndex


class ObservationError(Exception):
    """仅包含固定安全错误类别，不携带底层异常或输入值。"""


_ISSUES = {
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


class _AsciiTrim(Func):
    function = 'TRIM'
    output_field = TextField()

    def as_postgresql(self, compiler, connection, **extra_context):
        return super().as_sql(compiler, connection, function='BTRIM', **extra_context)


class _WarningsState(Func):
    """数据库内将列表投影为 0/1；非列表为 -1，原文不离开数据库。"""
    output_field = IntegerField()

    def as_sqlite(self, compiler, connection, **extra_context):
        return super().as_sql(compiler, connection, template=(
            "CASE WHEN json_type(%(expressions)s) = 'array' "
            "THEN CASE WHEN json_array_length(%(expressions)s) > 0 THEN 1 ELSE 0 END ELSE -1 END"
        ), **extra_context)

    def as_postgresql(self, compiler, connection, **extra_context):
        return super().as_sql(compiler, connection, template=(
            "CASE WHEN jsonb_typeof(%(expressions)s) = 'array' "
            "THEN CASE WHEN jsonb_array_length(%(expressions)s) > 0 THEN 1 ELSE 0 END ELSE -1 END"
        ), **extra_context)


class _InvalidEvidence(Func):
    """审核字段仅作类型/存在性检查；不读取姓名、时间值或正文。"""
    output_field = BooleanField()

    def as_sql(self, compiler, connection, **extra_context):
        parts = [compiler.compile(expression) for expression in self.source_expressions]
        text, flag, actor, stamp = [part[0] for part in parts]
        # All expressions here are column references, never user-provided SQL.
        if any(params for _, params in parts):
            raise ValueError('invalid_expression')
        if connection.vendor == 'sqlite':
            sql = (
                f"(typeof({text}) != 'text' OR typeof({flag}) != 'integer' OR {flag} NOT IN (0, 1) "
                f"OR ({actor} IS NOT NULL AND (typeof({actor}) != 'integer' OR {actor} <= 0)) "
                f"OR ({stamp} IS NOT NULL AND (typeof({stamp}) != 'text' "
                f"OR strftime('%%Y-%%m-%%d %%H:%%M:%%S', {stamp}) IS NULL)))"
            )
        elif connection.vendor == 'postgresql':
            sql = (f"({text} IS NULL OR {flag} IS NULL OR {actor} <= 0 "
                   f"OR ({stamp} IS NOT NULL AND NOT isfinite({stamp})))")
        else:
            raise ValueError('unsupported_database')
        return sql, []


def _queryset():
    nonempty = Q(GreaterThan(Length(_AsciiTrim(F('evidence__text'), Value('\t\n\v\f\r '))), Value(0)))
    flag = Q(evidence__review_required=True)
    by = Q(evidence__reviewed_by__isnull=False)
    at = Q(evidence__reviewed_at__isnull=False)
    complete = by & at
    incomplete = (by & ~at) | (~by & at) | (Q(format='pdf') & ~flag & ~complete) | (flag & complete)
    cohort = Q(format='pdf') | flag | by | at
    return MaterialVersion.objects.order_by().values('id', 'material_id', 'status', 'format').annotate(
        warning_state=_WarningsState(F('warnings')),
        structure_present=Exists(StructureIndex.objects.filter(version_id=OuterRef('pk'), is_current=True)),
        evidence_count=Count('evidence'),
        nonempty_count=Count('evidence', filter=nonempty),
        required_count=Count('evidence', filter=flag),
        reviewed_count=Count('evidence', filter=complete),
        incomplete_count=Count('evidence', filter=incomplete),
        cohort_count=Count('evidence', filter=cohort),
        completed_count=Count('evidence', filter=nonempty & ~flag & complete),
        invalid_count=Count('evidence', filter=_InvalidEvidence(
            F('evidence__text'), F('evidence__review_required'),
            F('evidence__reviewed_by'), F('evidence__reviewed_at'),
        )),
    )


def _report(row):
    count_names = ('evidence_count', 'nonempty_count', 'required_count', 'reviewed_count',
                   'incomplete_count', 'cohort_count', 'completed_count', 'invalid_count')
    total = row['evidence_count']
    if (any(type(row[name]) is not int or not 0 <= row[name] <= total for name in count_names)
            or row['invalid_count'] or row['format'] not in {'pdf', 'md'}
            or row['warning_state'] not in (0, 1)
            or row['completed_count'] > row['cohort_count']):
        raise ValueError('invalid_observation')
    status = row['status'] if row['status'] in MaterialVersion.Status.values else 'unknown'
    terminal = status in {'ready', 'needs_review'}
    empty = total - row['nonempty_count']
    missing_page = row['format'] == 'pdf' and empty > 0
    if not terminal or total == 0 or row['incomplete_count'] or missing_page:
        review = 'unknown'
    elif row['cohort_count'] == 0:
        review = 'not_required'
    elif row['completed_count'] == row['cohort_count']:
        review = 'complete'
    elif row['completed_count']:
        review = 'partial'
    else:
        review = 'unreviewed'
    triggers = {
        'unknown_processing_state': status == 'unknown',
        'parse_failed': status == 'failed',
        'no_evidence': terminal and total == 0,
        'no_text': terminal and total > 0 and row['nonempty_count'] == 0,
        'page_text_missing': terminal and missing_page,
        'evidence_review_required': terminal and row['required_count'] > 0,
        'review_metadata_incomplete': terminal and row['incomplete_count'] > 0,
        'legacy_status_needs_review': status == 'needs_review',
        'structure_missing': terminal and not row['structure_present'],
        'legacy_warning_present': row['warning_state'] == 1,
    }
    if status == 'unknown':
        assessment = 'unknown'
    elif status in {'queued', 'processing'}:
        assessment = 'pending'
    elif status == 'failed' or total == 0 or row['nonempty_count'] == 0:
        assessment = 'blocked'
    elif missing_page or row['required_count'] or row['incomplete_count'] or status == 'needs_review':
        assessment = 'needs_review'
    elif review not in {'not_required', 'complete'}:
        assessment = 'unknown'
    else:
        assessment = 'usable'
    return {
        'schema_version': 'ldb-material-quality-v1',
        'native_ref': {'material_id': row['material_id'], 'version_id': row['id']},
        'processing_state': status, 'assessment': assessment, 'review_state': review,
        'counts': {'evidence': total, 'nonempty': row['nonempty_count'], 'empty': empty,
                   'review_required': row['required_count'], 'reviewed': row['reviewed_count']},
        'structure_state': 'present' if row['structure_present'] else 'missing',
        'integrity_check': 'not_checked',
        'issues': [{'code': code, 'severity': _ISSUES[code][0], 'scope': _ISSUES[code][1]}
                   for code in sorted(_ISSUES) if triggers[code]],
    }


def observe_version_quality(user, material_id=None, version_id=None):
    """单 SELECT 中复用原生授权并观察；不读取或修改任何消费状态。"""
    error = None
    try:
        if not getattr(user, 'is_authenticated', False):
            error = 'authentication_required'
        elif any(type(value) is not int or not 0 < value <= 2**63 - 1 for value in (material_id, version_id)):
            error = 'invalid_arguments'
        else:
            row = selectors.get_version(user, material_id, version_id, queryset=_queryset())
            return _report(row)
    except Http404:
        error = 'object_unavailable'
    except Exception:
        error = 'observation_failed'
    # Raise outside the handler: even __context__ must not retain SQL or values.
    raise ObservationError(error)
