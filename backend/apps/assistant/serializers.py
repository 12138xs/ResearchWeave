from __future__ import annotations

from rest_framework import serializers

from apps.assistant.models import AssistantExchange, AssistantSession


class AssistantExchangeSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssistantExchange
        fields = [
            "id",
            "session",
            "question",
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
