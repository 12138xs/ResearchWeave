from __future__ import annotations

from django.utils import timezone
from rest_framework import serializers

from apps.quality.models import QualityIssue


class QualityIssueSerializer(serializers.ModelSerializer):
    reviewed_by_username = serializers.CharField(source="reviewed_by.username", read_only=True)

    class Meta:
        model = QualityIssue
        fields = [
            "id",
            "object_type",
            "object_id",
            "dimension",
            "severity",
            "status",
            "score",
            "notes",
            "evidence_json",
            "source_task",
            "reviewed_by",
            "reviewed_by_username",
            "reviewed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "object_type",
            "object_id",
            "source_task",
            "reviewed_by",
            "reviewed_at",
            "created_at",
            "updated_at",
        ]

    def update(self, instance, validated_data):
        request = self.context.get("request")
        if "status" in validated_data and request is not None:
            instance.reviewed_by = request.user
            instance.reviewed_at = timezone.now()
        return super().update(instance, validated_data)
