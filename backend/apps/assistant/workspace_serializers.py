from rest_framework import serializers

from apps.assistant.models import AssistantSession, PersonalEntry, PersonalProfile, ResearchPublication


class ProfileSerializer(serializers.ModelSerializer):
    style = serializers.CharField(max_length=2000, allow_blank=True, required=False)

    class Meta:
        model = PersonalProfile
        fields = ["style", "memory_enabled", "updated_at"]
        read_only_fields = ["updated_at"]


class EntrySerializer(serializers.ModelSerializer):
    body = serializers.CharField(max_length=12000)
    source_session = serializers.PrimaryKeyRelatedField(queryset=AssistantSession.objects.none(), required=False, allow_null=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["source_session"].queryset = AssistantSession.objects.filter(created_by=self.context["request"].user)

    def validate(self, data):
        kind = data.get("kind", self.instance.kind if self.instance else None)
        if self.instance and kind != self.instance.kind:
            raise serializers.ValidationError("记录类型不能修改。")
        if kind == "memory" and len(data.get("body", self.instance.body if self.instance else "")) > 500:
            raise serializers.ValidationError("每条记忆最多 500 字。")
        return data

    class Meta:
        model = PersonalEntry
        fields = ["id", "kind", "title", "body", "enabled", "status", "source_session", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class PublicationInput(serializers.Serializer):
    title = serializers.CharField(max_length=240)
    body = serializers.CharField(max_length=12000)
    evidence_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), max_length=32, default=list)
    request_id = serializers.UUIDField()
    reviewed = serializers.BooleanField()

    def validate_reviewed(self, value):
        if not value:
            raise serializers.ValidationError("请先核对共享正文及来源。")
        return value


class PublicationSerializer(serializers.ModelSerializer):
    can_delete = serializers.SerializerMethodField()

    def get_can_delete(self, obj):
        return obj.owner_id == self.context["request"].user.pk

    class Meta:
        model = ResearchPublication
        fields = ["id", "title", "body", "evidence_ids", "created_at", "can_delete"]
