from __future__ import annotations

from django.db import transaction
from rest_framework import serializers

from apps.documents.models import (
    Document,
    DocumentImportBatch,
    DocumentImportCandidate,
    DocumentSource,
    DocumentVersion,
)
from apps.library.models import KnowledgeSpace
from apps.documents.services.keywords import set_document_keywords


class DocumentSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentSource
        fields = [
            "id",
            "source_type",
            "title",
            "url",
            "storage_key",
            "content_hash",
            "raw_excerpt",
            "license_note",
            "attribution",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate(self, attrs):
        source_type = attrs.get("source_type")
        url = attrs.get("url", "")
        if source_type == DocumentSource.SourceType.URL:
            from apps.documents.importing import is_safe_external_url

            if not is_safe_external_url(url):
                raise serializers.ValidationError({"url": "Unsafe external URL."})
        return attrs


class DocumentSerializer(serializers.ModelSerializer):
    code = serializers.SerializerMethodField()
    keywords = serializers.SerializerMethodField()
    space = serializers.StringRelatedField()
    space_id = serializers.PrimaryKeyRelatedField(
        queryset=KnowledgeSpace.objects.filter(is_active=True),
        source="space",
        required=False,
        allow_null=True,
    )
    space_slug = serializers.SerializerMethodField()
    space_path = serializers.SerializerMethodField()
    markdown = serializers.CharField(required=False, allow_blank=True, write_only=True)
    current_version = serializers.SerializerMethodField()
    current_markdown = serializers.SerializerMethodField()
    sources = DocumentSourceSerializer(many=True, read_only=True)

    class Meta:
        model = Document
        fields = [
            "id",
            "code",
            "title",
            "slug",
            "summary",
            "status",
            "space",
            "space_id",
            "space_slug",
            "space_path",
            "keywords",
            "markdown",
            "current_markdown",
            "current_version",
            "sources",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "code",
            "slug",
            "space_slug",
            "space_path",
            "created_at",
            "updated_at",
            "current_version",
            "current_markdown",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["markdown"] = data.pop("current_markdown")
        return data

    def get_keywords(self, obj):
        return [keyword.name for keyword in obj.keywords.all()]

    def get_code(self, obj):
        return f"D{obj.id:06d}"

    def get_space_slug(self, obj):
        return obj.space.slug if obj.space else None

    def get_space_path(self, obj):
        return obj.space.path_label() if obj.space else None

    def get_current_version(self, obj):
        version = obj.versions.filter(is_current=True).first()
        return version.version if version else None

    def get_current_markdown(self, obj):
        version = obj.versions.filter(is_current=True).first()
        return version.markdown if version else ""

    def create(self, validated_data):
        markdown = validated_data.pop("markdown", "")
        keywords = self.initial_data.get("keywords", [])
        with transaction.atomic():
            document = Document.objects.create(**validated_data)
            set_document_keywords(document, keywords)
            DocumentVersion.objects.create(
                document=document,
                version=1,
                markdown=markdown,
                is_current=True,
            )
        return document

    def update(self, instance, validated_data):
        markdown_provided = "markdown" in validated_data
        markdown = validated_data.pop("markdown", "")
        keywords_provided = "keywords" in self.initial_data
        keywords = self.initial_data.get("keywords", [])
        with transaction.atomic():
            for field, value in validated_data.items():
                setattr(instance, field, value)
            instance.save()
            if keywords_provided:
                set_document_keywords(instance, keywords)
            if markdown_provided:
                current = instance.versions.filter(is_current=True).first()
                if not current or current.markdown != markdown:
                    instance.versions.filter(is_current=True).update(is_current=False)
                    version = (instance.versions.order_by("-version").first().version if instance.versions.exists() else 0) + 1
                    DocumentVersion.objects.create(
                        document=instance,
                        version=version,
                        markdown=markdown,
                        is_current=True,
                    )
        return instance


class DocumentListSerializer(serializers.ModelSerializer):
    code = serializers.SerializerMethodField()
    keywords = serializers.SerializerMethodField()
    space = serializers.StringRelatedField()
    space_slug = serializers.SerializerMethodField()
    space_path = serializers.SerializerMethodField()
    current_version = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            "id",
            "code",
            "title",
            "slug",
            "summary",
            "status",
            "space",
            "space_slug",
            "space_path",
            "keywords",
            "current_version",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_keywords(self, obj):
        return [keyword.name for keyword in obj.keywords.all()]

    def get_code(self, obj):
        return f"D{obj.id:06d}"

    def get_space_slug(self, obj):
        return obj.space.slug if obj.space else None

    def get_space_path(self, obj):
        return obj.space.path_label() if obj.space else None

    def get_current_version(self, obj):
        cached_versions = getattr(obj, "current_versions_cache", None)
        if cached_versions is not None:
            return cached_versions[0].version if cached_versions else None
        version = obj.versions.filter(is_current=True).only("version").first()
        return version.version if version else None


class DocumentImportCandidateSerializer(serializers.ModelSerializer):
    target_space = serializers.StringRelatedField(read_only=True)
    target_space_id = serializers.PrimaryKeyRelatedField(
        queryset=KnowledgeSpace.objects.filter(is_active=True),
        source="target_space",
        required=False,
        allow_null=True,
    )

    class Meta:
        model = DocumentImportCandidate
        fields = [
            "id",
            "batch",
            "source",
            "target_space",
            "target_space_id",
            "proposed_title",
            "proposed_summary",
            "proposed_markdown",
            "proposed_keywords",
            "quality_notes",
            "status",
            "confidence",
            "document",
            "reviewed_by",
            "reviewed_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "target_space",
            "status",
            "document",
            "reviewed_by",
            "reviewed_at",
            "created_at",
        ]

    def validate_proposed_keywords(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Expected a list of keywords.")
        return value


class DocumentImportBatchSerializer(serializers.ModelSerializer):
    target_space = serializers.StringRelatedField(read_only=True)
    target_space_id = serializers.PrimaryKeyRelatedField(
        queryset=KnowledgeSpace.objects.filter(is_active=True),
        source="target_space",
        required=False,
        allow_null=True,
    )
    sources = DocumentSourceSerializer(many=True, write_only=True, required=False)
    source_count = serializers.SerializerMethodField()
    candidate_count = serializers.SerializerMethodField()

    class Meta:
        model = DocumentImportBatch
        fields = [
            "id",
            "name",
            "source_mode",
            "target_space",
            "target_space_id",
            "status",
            "sources",
            "source_count",
            "candidate_count",
            "options_json",
            "error_message",
            "completed_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "target_space",
            "status",
            "source_count",
            "candidate_count",
            "error_message",
            "completed_at",
            "created_at",
        ]

    def get_source_count(self, obj):
        return obj.sources.count()

    def get_candidate_count(self, obj):
        return obj.candidates.count()

    def create(self, validated_data):
        source_payloads = validated_data.pop("sources", [])
        with transaction.atomic():
            batch = DocumentImportBatch.objects.create(**validated_data)
            for payload in source_payloads:
                source = DocumentSource.objects.create(**payload)
                batch.sources.add(source)
        return batch

