"""Bounded reads of already discovered, fixed-version evidence."""
from apps.assistant.knowledge import resolve_source, material_source, slice_source, source_allowed
from apps.materials.models import Evidence

MAX_READ_CHARS = 3000
MAX_EVIDENCE_CHARS = 18000
MAX_SOURCES = 16


def read_source(user, scope, source, *, budget=MAX_READ_CHARS, offset=0, context=False, before=0, after=1):
    if type(budget) is not int or not 1 <= budget <= MAX_READ_CHARS:
        raise ValueError("读取预算必须为 1–3000 字")
    if type(offset) is not int or offset < 0:
        raise ValueError("读取偏移必须为非负整数")
    if any(type(value) is not int or not 0 <= value <= 2 for value in (before, after)):
        raise ValueError("相邻范围前后各最多两项")
    current = resolve_source(source, user, scope)
    if offset > current['total_chars']:
        raise ValueError("偏移超出当前证据")
    if context:
        if source['type'] != 'material' or offset:
            raise ValueError("相邻读取仅支持材料固定版本；其他来源请用正文读取")
        rows = Evidence.objects.filter(version_id=current['version_id'],
            ordinal__gte=max(1, current['ordinal'] - before), ordinal__lte=current['ordinal'] + after,
        ).select_related('version__material').order_by('ordinal')
        originals = [material_source(row) for row in rows]
    else:
        originals = [current]
    output, remaining = [], budget
    for index, original in enumerate(originals):
        if not remaining:
            break
        allowance = max(1, remaining // (len(originals) - index))
        start = offset if not context else 0
        row = slice_source(original, start, allowance)
        row['next_offset'] = row['text_end'] if row['text_end'] < row['total_chars'] else None
        row['read_mode'] = 'context' if context else 'evidence'
        if not source_allowed(row, user):
            raise ValueError("读取期间来源发生变化")
        output.append(row)
        remaining -= len(row['excerpt'])
    return {'sources': output, 'truncated': len(output) < len(originals) or any(row['truncated'] for row in output),
            'returned_chars': budget - remaining, 'notice': '相邻页/片段不等于章节或整篇全文。' if context else '仅返回指定固定证据的有界正文。'}


def register_sources(registry, rows, remaining, *, max_sources=MAX_SOURCES):
    """Charge every emitted excerpt, including repeats; never silently replace a citation."""
    output, used, limited = [], 0, False
    for original in rows:
        if remaining <= 0:
            limited = True
            break
        row = dict(original)
        if len(row['excerpt']) > remaining:
            row['excerpt'] = row['excerpt'][:remaining]
            row['text_end'] = row.get('text_start', 0) + len(row['excerpt'])
            row['next_offset'] = row['text_end']
            row['truncated'] = True
            limited = True
        key = (row['type'], row['id'], row.get('text_start', 0), row['excerpt'])
        label = next((label for label, value in registry.items()
                      if (value['type'], value['id'], value.get('text_start', 0), value['excerpt']) == key), None)
        if label is None:
            if len(registry) >= max_sources:
                limited = True
                continue
            label = f'S{len(registry) + 1}'
            registry[label] = {**row, 'label': label}
        emitted = dict(registry[label])
        # Read metadata describes this operation even if it returned an existing excerpt.
        if 'read_mode' in row:
            emitted['read_mode'] = row['read_mode']
        output.append(emitted)
        used += len(emitted['excerpt'])
        remaining -= len(emitted['excerpt'])
    return output, used, limited
