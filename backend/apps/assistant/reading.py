"""Bounded reads of already discovered, fixed-version evidence."""
from apps.assistant.knowledge import resolve_source, material_source, chunk_source, slice_source, source_allowed, search_window
from apps.materials.models import Evidence, StructureChunk
from apps.search.evidence import ranked_candidates, query_terms

MAX_READ_CHARS = 3000
MAX_EVIDENCE_CHARS = 18000
MAX_SOURCES = 16


def find_in_source(user, scope, source, *, query, budget=MAX_READ_CHARS):
    """Search body text in one already-authorized immutable material version."""
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 500 or not query_terms(query):
        raise ValueError('定位查询必须为 1–500 字关键词')
    if type(budget) is not int or not 1 <= budget <= MAX_READ_CHARS:
        raise ValueError('读取预算必须为 1–3000 字')
    current = resolve_source(source, user, scope)
    if current['type'] != 'material':
        return {'sources': [], 'notice': '此来源没有材料分页版本，请使用 read_evidence 读取已有正文。'}
    if current.get('chunk_id'):
        rows = ranked_candidates(StructureChunk.objects.filter(index_id=current['structure_index_id']).select_related('index__version__material'), query, [('text', 10), ('title_path', 8)], limit=3)
    else:
        rows = ranked_candidates(Evidence.objects.filter(version_id=current['version_id'], text__regex=r'\S')
                                 .select_related('version__material'), query, [('text', 10)], limit=3)
    output, remaining = [], budget
    for row in rows:
        if remaining <= 0:
            break
        window = search_window(chunk_source(row) if current.get("chunk_id") else material_source(row), query, query_terms(query))
        if len(window['excerpt']) > remaining:
            window['excerpt'] = window['excerpt'][:remaining]
            window['text_end'] = window['text_start'] + len(window['excerpt'])
            window['truncated'] = True
        window['next_offset'] = window['text_end'] if window['text_end'] < window['total_chars'] else None
        window['read_mode'] = 'within_source_search'
        if not source_allowed(window, user, scope):
            raise ValueError('定位期间来源发生变化')
        output.append(window)
        remaining -= len(window['excerpt'])
    return {'sources': output, 'returned_chars': budget - remaining,
            'truncated': len(output) < len(rows) or any(row['truncated'] for row in output),
            'notice': '只在已发现的固定版本正文内匹配，最多三个片段，不表示整篇已读完。'}


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
        if current.get('chunk_id'):
            chunk = StructureChunk.objects.get(pk=current['chunk_id'])
            rows = StructureChunk.objects.filter(index_id=chunk.index_id, section=chunk.section,
                ordinal__gte=max(1, chunk.ordinal - before), ordinal__lte=chunk.ordinal + after).select_related('index__version__material').order_by('ordinal')
            originals = [chunk_source(row) for row in rows]
        else:
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
        if not source_allowed(row, user, scope):
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
        key = (row['type'], row['id'], row.get('chunk_id'), row.get('text_start', 0), row['excerpt'])
        label = next((label for label, value in registry.items()
                      if (value['type'], value['id'], value.get('chunk_id'), value.get('text_start', 0), value['excerpt']) == key), None)
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
