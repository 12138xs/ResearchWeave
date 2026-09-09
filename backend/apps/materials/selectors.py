from django.shortcuts import get_object_or_404

from apps.common.permissions import editable_by, visible_to
from apps.materials.models import Material, MaterialVersion


def materials(user, write=False):
    return (editable_by if write else visible_to)(Material.objects.all(), user)


def version_data(version):
    return {
        "id": version.pk, "number": version.number, "filename": version.filename,
        "format": version.format, "sha256": version.sha256, "size": version.size,
        "status": version.status, "error": version.error, "warnings": version.warnings,
        "parser_version": version.parser_version, "created_at": version.created_at,
        "file_url": f"/api/materials/{version.material_id}/versions/{version.pk}/file/",
    }


def material_data(material, user):
    return {
        "id": material.pk, "title": material.title, "visibility": material.visibility,
        "can_edit": material.owner_id == user.pk or (user.is_staff and material.visibility == "team"),
        "versions": [version_data(version) for version in material.versions.all()],
    }


def get_version(user, pk, version_id, write=False, lock=False):
    allowed = materials(user, write=write).values("pk")
    queryset = MaterialVersion.objects.filter(material_id__in=allowed)
    if lock:
        queryset = queryset.select_for_update()
    return get_object_or_404(queryset, pk=version_id, material_id=pk)


