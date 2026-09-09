from __future__ import annotations

from rest_framework import serializers

from apps.assistant.models import AssistantExchange, AssistantSession
from apps.experiments.selectors import accessible_experiments
from apps.papers.models import Paper
from apps.documents.models import Document
from apps.library.models import KnowledgeSpace
from apps.materials.selectors import materials
from apps.assistant.knowledge import source_allowed


def validate_scope(scope, user):
    if not isinstance(scope, dict):
        raise serializers.ValidationError("来源范围必须是对象。")
    sources = {
        "material_ids": materials(user),
        "paper_ids": Paper.objects.all(), "document_ids": Document.objects.all(),
        "experiment_ids": accessible_experiments(user), "space_ids": KnowledgeSpace.objects.filter(is_active=True),
    }
    for key, ids in scope.items():
        if key not in sources or not isinstance(ids, list) or len(ids) > 100:
            raise serializers.ValidationError("来源范围不合法。")
        if any(type(value) is not int or value <= 0 for value in ids):
            raise serializers.ValidationError("来源编号必须是正整数。")
        if sources[key].filter(pk__in=ids).count() != len(set(ids)):
            raise serializers.ValidationError("部分来源不存在或不可访问。")
    return scope


class AssistantExchangeSerializer(serializers.ModelSerializer):
    def to_representation(self, instance):
        data = super().to_representation(instance)
        if any(not source_allowed(source, instance.session.created_by) for source in instance.sources):
            data.update(answer="部分引用已不可访问，历史回答已隐藏。", sources=[], context_warning="请重新检索当前可用材料。")
        return data

    class Meta:
        model = AssistantExchange
        fields = [
            "id",
            "session",
            "question",
            "request_id", "status", "attempt", "progress", "error", "updated_at",
            "answer",
            "sources",
            "model",
            "usage",
            "context_warning",
            "created_at",
        ]
        read_only_fields = ["id", "session", "answer", "sources", "model", "usage", "context_warning", "created_at"]


class AssistantSessionSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    exchanges = AssistantExchangeSerializer(many=True, read_only=True)

    def validate_scope_json(self, value):
        return validate_scope(value, self.context["request"].user)

    class Meta:
        model = AssistantSession
        fields = [
            "id",
            "title",
            "mode",
            "scope_json",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
            "exchanges",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at", "exchanges"]


class AssistantMessageInputSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=4000, trim_whitespace=True)
    request_id = serializers.UUIDField()
