from rest_framework import serializers

from apps.agent_access.contracts import SourceKind
from apps.agent_access.models import KNOWN_SCOPES


class TokenIssueSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    scopes = serializers.ListField(
        child=serializers.ChoiceField(choices=sorted(KNOWN_SCOPES)),
        allow_empty=False,
        max_length=len(KNOWN_SCOPES),
    )
    expires_at = serializers.DateTimeField(required=False, allow_null=True)

    def validate_expires_at(self, value):
        from django.utils import timezone

        if value is not None and value <= timezone.now():
            raise serializers.ValidationError("过期时间必须晚于当前时间。")
        return value


class ExternalAccessUpdateSerializer(serializers.Serializer):
    source_kind = serializers.ChoiceField(choices=SourceKind.choices)
    allowed = serializers.BooleanField()


class EvidenceSearchSerializer(serializers.Serializer):
    q = serializers.CharField(max_length=500)
    limit = serializers.IntegerField(default=10, min_value=1, max_value=25)
    material_id = serializers.IntegerField(required=False, min_value=1)


class ContextBundleCreateSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=2000)
    material_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        default=list,
        max_length=50,
    )
    limit = serializers.IntegerField(default=10, min_value=1, max_value=25)
