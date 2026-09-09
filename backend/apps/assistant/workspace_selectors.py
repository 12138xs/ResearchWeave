import hashlib
import json

from apps.assistant.models import PersonalEntry, PersonalProfile
from apps.materials.models import Evidence


def personal_context(user):
    profile = PersonalProfile.objects.filter(owner=user).first()
    style = profile.style if profile else ""
    enabled = profile.memory_enabled if profile else True
    memories = list(PersonalEntry.objects.filter(owner=user, kind="memory", enabled=True).order_by("pk").values("id", "body")[:20]) if enabled else []
    content = json.dumps({"style": style, "memories": memories}, ensure_ascii=False) if style or memories else ""
    return content, hashlib.sha256(content.encode()).hexdigest() if content else ""


def publication_allowed(publication):
    ids = publication.evidence_ids
    return Evidence.objects.filter(pk__in=ids, version__material__visibility="team").count() == len(set(ids))
