"""Derived Markdown indexes; original document versions remain authoritative."""
from django.db import transaction

from apps.materials.structure import PARSER_VERSION, digest, split_markdown
from apps.documents.models import DocumentVersion, DocumentStructureIndex, DocumentStructureChunk


@transaction.atomic
def build_structure(version_id):
    version = DocumentVersion.objects.select_for_update().get(pk=version_id)
    if len(version.markdown) > 4_000_000:
        raise ValueError('结构正文超出限制')
    source_hash = digest(version.markdown)
    index = version.structure_indexes.filter(parser_version=PARSER_VERSION, source_sha256=source_hash).first()
    if not index:
        sections, parts = split_markdown(version.markdown)
        index = DocumentStructureIndex.objects.create(version=version, parser_version=PARSER_VERSION,
            source_sha256=source_hash, sections=sections)
        DocumentStructureChunk.objects.bulk_create([
            DocumentStructureChunk(index=index, ordinal=n, section=part['section'],
                title_path=part['title_path'], text=part['text'], line_start=part['start'] + 1,
                line_end=part['end'], oversized=part['oversized'])
            for n, part in enumerate(parts, 1)
        ])
    version.structure_indexes.filter(is_current=True).exclude(pk=index.pk).update(is_current=False)
    if not index.is_current:
        index.is_current = True
        index.save(update_fields=['is_current'])
    return index


def verified_chunk_text(chunk):
    text = chunk.index.version.markdown
    if digest(text) != chunk.index.source_sha256:
        raise ValueError('文档版本正文已变化')
    original = ''.join(text.splitlines(keepends=True)[chunk.line_start - 1:chunk.line_end])
    if original != chunk.text:
        raise ValueError('分片与文档原文不一致')
    return original
