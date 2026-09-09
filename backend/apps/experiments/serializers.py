from __future__ import annotations

from rest_framework import serializers

from apps.documents.models import Document
from apps.experiments.models import ExperimentProject, ExperimentRun
from apps.library.models import KnowledgeSpace
from apps.papers.models import Paper


class ExperimentRunSerializer(serializers.ModelSerializer):
    created_by_username = serializers.SerializerMethodField()

    class Meta:
        model = ExperimentRun
        fields = [
            "id",
            "project",
            "status",
            "params_json",
            "metrics_json",
            "artifact_keys",
            "notes",
            "started_at",
            "finished_at",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "project", "created_by", "created_at", "updated_at"]

    def get_created_by_username(self, obj):
        return obj.created_by.username if obj.created_by else None


class ExperimentProjectSerializer(serializers.ModelSerializer):
    owner_username = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    paper_title = serializers.CharField(source="paper.title", read_only=True)
    document_title = serializers.CharField(source="document.title", read_only=True)
    space_path = serializers.SerializerMethodField()
    paper = serializers.PrimaryKeyRelatedField(queryset=Paper.objects.all(), required=False, allow_null=True)
    document = serializers.PrimaryKeyRelatedField(queryset=Document.objects.all(), required=False, allow_null=True)
    space = serializers.PrimaryKeyRelatedField(
        queryset=KnowledgeSpace.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    runs = ExperimentRunSerializer(many=True, read_only=True)

    class Meta:
        model = ExperimentProject
        fields = [
            "id",
            "title",
            "visibility",
            "slug",
            "paper",
            "paper_title",
            "document",
            "document_title",
            "space",
            "space_path",
            "status",
            "owner",
            "owner_username",
            "can_edit",
            "objective",
            "protocol_markdown",
            "repo_url",
            "environment_json",
            "runs",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "slug", "owner", "created_at", "updated_at"]

    def get_owner_username(self, obj):
        return obj.owner.username if obj.owner else None

    def get_can_edit(self, obj):
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return False
        return obj.owner_id == request.user.pk or (obj.visibility == "team" and request.user.is_staff)

    def get_space_path(self, obj):
        return obj.space.path_label() if obj.space else None
