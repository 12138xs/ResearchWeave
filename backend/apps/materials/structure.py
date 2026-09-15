"""Versioned Markdown structure over unchanged canonical Evidence text."""
import hashlib
import re

from django.db import transaction
from markdown_it import MarkdownIt
from apps.materials.models import MaterialVersion, StructureIndex, StructureChunk

PARSER_VERSION = 'markdown-it4-blocks-v1'
TARGET_CHARS = 1600


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def split_markdown(text):
    lines = text.splitlines(keepends=True)
    tokens = MarkdownIt('commonmark').enable('table').parse(text)
    protected = [(t.map[0], t.map[1]) for t in tokens if t.map and t.type in {'fence', 'code_block'}]
    if lines and lines[0].strip() == '---':
        end = next((i for i in range(1, len(lines)) if lines[i].strip() in {'---', '...'}), None)
        if end is not None:
            protected.append((0, end + 1))
    closing, start = None, 0
    for i, line in enumerate(lines):
        if any(a <= i < b for a, b in protected):
            continue
        value = line.strip()
        if closing:
            if value == closing:
                protected.append((start, i + 1)); closing = None
        elif value in {'$$', r'\['}:
            start, closing = i, '$$' if value == '$$' else r'\]'
        elif re.fullmatch(r'\\begin\{(?:equation\*?|align\*?|gather\*?|multline\*?)\}', value):
            start, closing = i, value.replace('begin', 'end', 1)
    if closing:
        protected.append((start, len(lines)))
    def interior(i):
        return any(a < i < b for a, b in protected)
    headings = {}
    for i, token in enumerate(tokens):
        if token.type == 'heading_open' and token.level == 0 and token.map and not interior(token.map[0]):
            headings[token.map[0]] = (int(token.tag[1:]), tokens[i + 1].content)
    boundaries = {0, len(lines)}
    boundaries.update(t.map[0] for t in tokens if t.map and t.level == 0 and not interior(t.map[0]))
    boundaries.update(a for a, _ in protected)
    boundaries = sorted(boundaries)
    sections, stack, chunks = [], [], []
    current = None
    def flush():
        nonlocal current
        if current is not None:
            current['text'] = ''.join(lines[current['start']:current['end']])
            current['oversized'] = len(current['text']) > TARGET_CHARS
            chunks.append(current); current = None
    for a, b in zip(boundaries, boundaries[1:]):
        if a in headings:
            flush()
            level, title = headings[a]
            while stack and sections[stack[-1] - 1]['level'] >= level:
                sections[stack.pop() - 1]['line_end'] = a
            item = {'id': len(sections) + 1, 'parent': stack[-1] if stack else None,
                    'level': level, 'title': title, 'line_start': a + 1, 'line_end': len(lines)}
            sections.append(item); stack.append(item['id'])
        path = ' / '.join(sections[n - 1]['title'] for n in stack)
        if current and len(''.join(lines[current['start']:b])) > TARGET_CHARS:
            flush()
        if current is None:
            current = {'start': a, 'end': b, 'section': stack[-1] if stack else 0, 'title_path': path}
        else:
            current['end'] = b
    flush()
    assert ''.join(c['text'] for c in chunks) == text
    return sections, chunks


def canonical(version):
    rows = list(version.evidence.order_by('ordinal'))
    expected = 1
    for row in rows:
        if row.page or row.line_start != expected or row.line_end != row.line_start + len(row.text.split('\n')) - 1:
            raise ValueError('证据行号不连续，不能构建结构索引')
        expected = row.line_end + 1
    return '\n'.join(row.text for row in rows), rows


@transaction.atomic
def build_structure(version_id):
    version = MaterialVersion.objects.select_for_update().get(pk=version_id)
    if version.format != 'md' or version.status not in {'ready', 'needs_review'}:
        return None
    text, evidence = canonical(version)
    if len(text) > 4_000_000:
        raise ValueError('结构正文超出限制')
    source_hash = digest(text)
    old = version.structure_indexes.filter(parser_version=PARSER_VERSION, source_sha256=source_hash).first()
    if old:
        version.structure_indexes.filter(is_current=True).exclude(pk=old.pk).update(is_current=False)
        if not old.is_current:
            old.is_current = True; old.save(update_fields=['is_current'])
        return old
    sections, parts = split_markdown(text)
    index = StructureIndex.objects.create(version=version, parser_version=PARSER_VERSION, source_sha256=source_hash, sections=sections)
    chunks = []
    for n, part in enumerate(parts, 1):
        a, b = part['start'] + 1, part['end']
        ids = [e.pk for e in evidence if e.line_start <= b and e.line_end >= a]
        chunks.append(StructureChunk(index=index, ordinal=n, section=part['section'], title_path=part['title_path'],
            text=part['text'], line_start=a, line_end=b, evidence_ids=ids, oversized=part['oversized']))
    StructureChunk.objects.bulk_create(chunks)
    version.structure_indexes.filter(is_current=True).update(is_current=False)
    index.is_current = True; index.save(update_fields=['is_current'])
    return index


def verified_chunk_text(chunk):
    rows = list(chunk.index.version.evidence.filter(pk__in=chunk.evidence_ids).order_by('ordinal'))
    if not rows or [r.pk for r in rows] != chunk.evidence_ids:
        raise ValueError('分片原始证据已变化')
    lines = '\n'.join(r.text for r in rows).split('\n')
    start = chunk.line_start - rows[0].line_start
    count = chunk.line_end - chunk.line_start + 1
    text = '\n'.join(lines[start:start + count])
    # Non-final spans include their separator in the canonical stream.
    if chunk.text.endswith('\n'):
        text += '\n'
    if text != chunk.text:
        raise ValueError('分片与原始证据不一致')
    return text
