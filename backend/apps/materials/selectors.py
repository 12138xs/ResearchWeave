from django.shortcuts import get_object_or_404

from apps.common.permissions import editable_by, visible_to
from apps.materials.models import Material, MaterialVersion


def materials(user, write=False):
    return (editable_by if write else visible_to)(Material.objects.all(), user)


def retrieval_status(version):
    if version.status not in {"ready", "needs_review"}:
        return "unavailable"
    if not version.evidence.filter(text__regex=r"\S").exists():
        return "no_text"
    return "searchable_review" if version.status == "needs_review" else "searchable"


def version_data(version):
    return {
        "id": version.pk, "number": version.number, "filename": version.filename,
        "format": version.format, "sha256": version.sha256, "size": version.size,
        "retrieval_status": retrieval_status(version),
        "status": version.status, "error": version.error, "warnings": version.warnings,
        "parser_version": version.parser_version, "created_at": version.created_at,
        "file_url": f"/api/materials/{version.material_id}/versions/{version.pk}/file/",
    }


def material_data(material, user):
    return {
        "content_type": material.content_type, "content_type_label": material.get_content_type_display(),
        "internal_ai_blocked": material.internal_ai_blocked or material.content_type == "proposal",
        "id": material.pk, "title": material.title, "visibility": material.visibility,
        "can_classify": material.owner_id == user.pk, "source_kind": material.source_kind, "source_kind_label": material.get_source_kind_display(),
        "legacy_paper_ids": list(material.versions.values_list("legacy_links__paper_id", flat=True).exclude(legacy_links__paper_id=None).distinct()),
        "can_edit": material.owner_id == user.pk or (user.is_staff and material.visibility == "team"),
        "versions": [version_data(version) for version in material.versions.all()],
    }


def get_version(user, pk, version_id, write=False, lock=False):
    allowed = materials(user, write=write).values("pk")
    queryset = MaterialVersion.objects.filter(material_id__in=allowed)
    if lock:
        queryset = queryset.select_for_update()
    return get_object_or_404(queryset, pk=version_id, material_id=pk)


