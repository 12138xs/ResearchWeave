from rest_framework import serializers
from apps.agent_access.contracts import SourceKind
from apps.materials.models import ContentType


class UploadSerializer(serializers.Serializer):
    content_type = serializers.ChoiceField(choices=ContentType.choices, default=ContentType.OTHER)
    source_kind = serializers.ChoiceField(choices=SourceKind.choices, default=SourceKind.UNCLASSIFIED)
    file = serializers.FileField()
    title = serializers.CharField(max_length=500, required=False, default="", allow_blank=True)
    visibility = serializers.ChoiceField(choices=["team", "private"], default="team")


class CardSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=300)
    markdown = serializers.CharField(max_length=100_000)
    evidence_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), min_length=1, max_length=100)


