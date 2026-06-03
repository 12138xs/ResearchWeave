from __future__ import annotations

from rest_framework import serializers

from apps.ai.models import PaperQAExchange


class PaperQAExchangeSerializer(serializers.ModelSerializer):
    username = serializers.SerializerMethodField()

    class Meta:
        model = PaperQAExchange
        fields = [
            "id",
            "paper",
            "username",
            "question",
            "answer",
            "mode",
            "model",
            "usage",
            "sources",
            "context_warning",
            "created_at",
        ]
        read_only_fields = fields

    def get_username(self, obj):
        return obj.user.username if obj.user else ""
