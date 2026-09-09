from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from apps.assistant.models import AssistantSession, PersonalEntry, PersonalProfile, ResearchPublication
from apps.assistant.services import Conflict, sync_task
from apps.assistant.workspace_selectors import publication_allowed


def save_profile(user, data):
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        profile, _ = PersonalProfile.objects.get_or_create(owner=user)
        for key, value in data.items():
            setattr(profile, key, value)
        profile.save()
        return profile


def save_entry(user, data, instance=None):
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        if instance:
            instance = get_object_or_404(PersonalEntry.objects.select_for_update(), pk=instance.pk, owner=user)
        source = data.get("source_session")
        if source is not None and not AssistantSession.objects.filter(pk=source.pk, created_by=user).exists():
            raise ValidationError("来源会话不存在或不可访问。")
        kind = data.get("kind", instance.kind if instance else None)
        enabled = data.get("enabled", instance.enabled if instance else True)
        if kind == "memory" and enabled:
            active = PersonalEntry.objects.filter(owner=user, kind="memory", enabled=True)
            if instance:
                active = active.exclude(pk=instance.pk)
            if active.count() >= 20:
                raise ValidationError("最多启用 20 条记忆，请先停用或整理已有记忆。")
        if instance is None:
            instance = PersonalEntry(owner=user)
        for key, value in data.items():
            setattr(instance, key, value)
        instance.save()
        return instance


def publish_entry(user, entry, data):
    values = {key: value for key, value in data.items() if key != "reviewed"}
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        get_object_or_404(PersonalEntry.objects.select_for_update(), pk=entry.pk, owner=user, kind="note")
        previous = ResearchPublication.objects.filter(owner=user, request_id=data["request_id"]).first()
        if previous:
            if previous.source_entry_id != entry.pk or any(getattr(previous, key) != value for key, value in values.items()):
                raise Conflict("同一发布编号不能用于不同内容。")
            return previous
        publication = ResearchPublication(owner=user, source_entry=entry, **values)
        if not publication_allowed(publication):
            raise ValidationError("发布只能引用当前团队共享的原文证据。")
        publication.save()
        return publication


def delete_session(session):
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=session.created_by_id)
        session = AssistantSession.objects.select_for_update().get(pk=session.pk)
        for row in session.exchanges.select_for_update().filter(status__in=["queued", "running"]):
            row.status, row.progress = "cancelled", "来源会话已删除"
            row.save(update_fields=["status", "progress", "updated_at"])
            sync_task(row)
        PersonalEntry.objects.filter(owner=session.created_by, source_session=session, kind="memory").delete()
        session.delete()
