"""Conservative native-outline anchors over unchanged PDF page evidence."""
import hashlib
import re

from pypdf import PdfReader
from apps.storage.provider import get_storage_provider

PARSER_VERSION = 'pdf-native-outline-lines-v1'


def title_key(value):
    value = re.sub(r'^\s*\d+(?:\.\d+)*\.?\s*', '', value)
    return re.sub(r'\s+', '', value).casefold()


def outline_entries(reader, items=None, depth=1):
    for item in reader.outline if items is None else items:
        if isinstance(item, list):
            yield from outline_entries(reader, item, depth + 1)
        else:
            page = reader.get_destination_page_number(item)
            yield {'page': page + 1 if page is not None else None, 'title': str(item.title), 'level': depth}


def split_pdf_pages(text, evidence, entries):
    """Unmatched outline destinations invalidate that page and inherited heading."""
    if any(e['page'] is None or e['page'] < 1 or e['page'] > len(evidence) for e in entries):
        entries = []  # Unknown destinations cannot safely delimit a chapter.
    if [e['page'] for e in entries] != sorted(e['page'] for e in entries):
        entries = []
    by_page = {}
    for entry in entries:
        by_page.setdefault(entry['page'], []).append(entry)
    lines = text.split('\n')
    sections, parts, stack = [], [], []
    for row in evidence:
        local = row.text.split('\n')
        anchors, invalid = [], False
        for entry in by_page.get(row.page, []):
            key = title_key(entry['title'])
            matches = [n for n, line in enumerate(local) if key and title_key(line) == key]
            if len(matches) != 1:
                invalid = True
                break
            anchors.append((matches[0], entry))
        positions = [n for n, _ in anchors]
        if positions != sorted(set(positions)):
            invalid = True
        if invalid:
            stack = []
            anchors = []
        starts = {n: entry for n, entry in anchors}
        boundaries = sorted({0, len(local), *starts})
        for a, b in zip(boundaries, boundaries[1:]):
            if a in starts:
                entry = starts[a]
                while stack and sections[stack[-1] - 1]['level'] >= entry['level']:
                    stack.pop()
                section = {'id': len(sections) + 1, 'parent': stack[-1] if stack else None,
                    'level': entry['level'], 'title': entry['title'], 'page': row.page,
                    'line_start': row.line_start + a, 'method': 'native_outline_unique_text',
                    'review_required': True}
                sections.append(section)
                stack.append(section['id'])
            start, end = row.line_start - 1 + a, row.line_start - 1 + b
            fragment = '\n'.join(lines[start:end])
            if end < len(lines):
                fragment += '\n'
            parts.append({'start': start, 'end': end, 'text': fragment,
                'section': stack[-1] if stack else 0,
                'title_path': ' / '.join(sections[n - 1]['title'] for n in stack),
                'oversized': len(fragment) > 1600})
    assert ''.join(part['text'] for part in parts) == text
    return sections, parts


def extract_outline(version):
    path = get_storage_provider().resolve(version.storage_key)
    if hashlib.sha256(path.read_bytes()).hexdigest() != version.sha256:
        raise ValueError('PDF原文件哈希不一致')
    reader = PdfReader(path)
    if reader.is_encrypted or len(reader.pages) > 500:
        raise ValueError('PDF不可解析')
    return list(outline_entries(reader))
