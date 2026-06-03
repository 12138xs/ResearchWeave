from __future__ import annotations

from io import BytesIO

from django.conf import settings
from pypdf import PdfReader
from rest_framework import serializers

from apps.library.keywords import canonical_keyword_names, get_or_create_canonical_keyword
from apps.papers.models import Paper, PaperDeepProfile, PaperLightProfile, PaperReadingState, ReadingReview
from apps.tasks.models import TaskRecord
from apps.tasks.serializers import TaskRecordSerializer


class PaperLightProfileSerializer(serializers.ModelSerializer):
    keywords = serializers.SerializerMethodField()

    class Meta:
        model = PaperLightProfile
        fields = [
            "id",
            "version",
            "is_active",
            "generator",
            "keywords",
            "background",
            "method",
            "results",
            "source_text_preview",
            "created_at",
        ]

    def get_keywords(self, obj):
        return canonical_keyword_names(obj.keywords)


class PaperDeepProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaperDeepProfile
        fields = [
            "id",
            "version",
            "is_active",
            "parser_name",
            "summary",
            "sections",
            "figures",
            "formulas",
            "code_suggestions",
            "reproduction_notes",
            "created_at",
        ]


class PaperReadingStateSerializer(serializers.ModelSerializer):
    owner_username = serializers.SerializerMethodField()
    updated_by_username = serializers.SerializerMethodField()

    class Meta:
        model = PaperReadingState
        fields = [
            "id",
            "paper",
            "reading_status",
            "reproduction_status",
            "owner",
            "owner_username",
            "next_step",
            "due_at",
            "updated_by",
            "updated_by_username",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "paper", "updated_by", "created_at", "updated_at"]

    def get_owner_username(self, obj):
        return obj.owner.username if obj.owner else None

    def get_updated_by_username(self, obj):
        return obj.updated_by.username if obj.updated_by else None


class ReadingReviewSerializer(serializers.ModelSerializer):
    reviewed_by_username = serializers.SerializerMethodField()

    class Meta:
        model = ReadingReview
        fields = [
            "id",
            "paper",
            "profile_type",
            "profile_id",
            "status",
            "score",
            "notes",
            "reviewed_by",
            "reviewed_by_username",
            "reviewed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "paper", "reviewed_by", "reviewed_at", "created_at", "updated_at"]

    def validate_score(self, value):
        if value is not None and (value < 0 or value > 100):
            raise serializers.ValidationError("Score must be between 0 and 100.")
        return value

    def get_reviewed_by_username(self, obj):
        return obj.reviewed_by.username if obj.reviewed_by else None


class PaperSerializer(serializers.ModelSerializer):
    code = serializers.SerializerMethodField()
    keywords = serializers.SerializerMethodField()
    space = serializers.StringRelatedField()
    space_id = serializers.IntegerField(read_only=True)
    space_slug = serializers.SerializerMethodField()
    space_path = serializers.SerializerMethodField()
    light_profile = serializers.SerializerMethodField()
    deep_profile = serializers.SerializerMethodField()
    active_deep_task = serializers.SerializerMethodField()
    has_pdf = serializers.SerializerMethodField()
    reading_state = serializers.SerializerMethodField()

    class Meta:
        model = Paper
        fields = [
            "id",
            "code",
            "title",
            "slug",
            "authors",
            "publication_type",
            "year",
            "venue",
            "volume",
            "issue",
            "pages",
            "area",
            "abstract",
            "doi",
            "arxiv_id",
            "source_url",
            "status",
            "code_status",
            "space",
            "space_id",
            "space_slug",
            "space_path",
            "keywords",
            "light_profile",
            "deep_profile",
            "active_deep_task",
            "has_pdf",
            "reading_state",
            "created_at",
            "updated_at",
        ]

    def get_code(self, obj):
        display_numbers = self.context.get("paper_display_numbers") if hasattr(self, "context") else None
        number = display_numbers.get(obj.id) if isinstance(display_numbers, dict) else None
        if number is None:
            number = _paper_display_number(obj)
        return f"P{number:06d}"

    def get_keywords(self, obj):
        return canonical_keyword_names([keyword.name for keyword in obj.keywords.all()])

    def get_space_slug(self, obj):
        return obj.space.slug if obj.space else None

    def get_space_path(self, obj):
        return obj.space.path_label() if obj.space else None

    def get_light_profile(self, obj):
        profile = obj.light_profiles.filter(is_active=True).first()
        if not profile:
            return None
        return PaperLightProfileSerializer(profile).data

    def get_deep_profile(self, obj):
        profile = obj.deep_profiles.filter(is_active=True).first()
        if not profile:
            return None
        return PaperDeepProfileSerializer(profile).data

    def get_active_deep_task(self, obj):
        task = (
            TaskRecord.objects.filter(
                object_type="paper",
                object_id=obj.id,
                task_type="deep_process_paper",
                status__in=[TaskRecord.Status.PENDING, TaskRecord.Status.RUNNING],
            )
            .order_by("-updated_at", "-id")
            .first()
        )
        if not task:
            return None
        return TaskRecordSerializer(task).data

    def get_has_pdf(self, obj):
        return bool(obj.source_pdf_path)

    def get_reading_state(self, obj):
        state = getattr(obj, "reading_state", None)
        if not state:
            return None
        return PaperReadingStateSerializer(state).data


class BlankableIntegerField(serializers.IntegerField):
    def run_validation(self, data=serializers.empty):
        if data == "":
            data = None
        return super().run_validation(data)


class PaperMetadataUpdateSerializer(serializers.ModelSerializer):
    year = BlankableIntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=9999,
    )
    publication_type = serializers.ChoiceField(
        choices=Paper.PublicationType.choices,
        required=False,
    )
    venue = serializers.CharField(
        max_length=180, allow_blank=True, allow_null=True, required=False
    )
    volume = serializers.CharField(
        max_length=60, allow_blank=True, allow_null=True, required=False
    )
    issue = serializers.CharField(
        max_length=60, allow_blank=True, allow_null=True, required=False
    )
    pages = serializers.CharField(
        max_length=80, allow_blank=True, allow_null=True, required=False
    )
    area = serializers.CharField(
        max_length=160, allow_blank=True, allow_null=True, required=False
    )
    abstract = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    doi = serializers.CharField(
        max_length=160, allow_blank=True, allow_null=True, required=False
    )
    arxiv_id = serializers.CharField(
        max_length=80, allow_blank=True, allow_null=True, required=False
    )
    source_url = serializers.URLField(
        max_length=500, allow_blank=True, allow_null=True, required=False
    )
    code_status = serializers.ChoiceField(
        choices=Paper.CodeStatus.choices,
        required=False,
    )
    keywords = serializers.ListField(
        child=serializers.CharField(max_length=80, allow_blank=True, allow_null=True),
        required=False,
        allow_empty=True,
        allow_null=True,
    )

    class Meta:
        model = Paper
        fields = [
            "title",
            "authors",
            "publication_type",
            "year",
            "venue",
            "volume",
            "issue",
            "pages",
            "area",
            "abstract",
            "doi",
            "arxiv_id",
            "source_url",
            "code_status",
            "keywords",
        ]

    def validate_authors(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Expected a list of author names.")
        return [str(item).strip() for item in value if str(item).strip()]

    def validate_title(self, value):
        title = str(value or "").strip()
        if len(title) < 3:
            raise serializers.ValidationError("Title is too short.")
        return title

    def validate_keywords(self, value):
        if value is None:
            return []
        return [str(item).strip() for item in value if str(item or "").strip()]

    def validate(self, attrs):
        for field in (
            "venue",
            "volume",
            "issue",
            "pages",
            "area",
            "abstract",
            "doi",
            "arxiv_id",
            "source_url",
        ):
            if field in attrs and attrs[field] is None:
                attrs[field] = ""
        return attrs

    def update(self, instance, validated_data):
        keyword_values = validated_data.pop("keywords", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if keyword_values is not None:
            keywords = [
                get_or_create_canonical_keyword(value)
                for value in canonical_keyword_names([str(value).strip() for value in keyword_values])
                if str(value).strip()
            ]
            instance.keywords.set(keywords)
        return instance


def _paper_display_number(paper: Paper) -> int:
    return Paper.objects.filter(id__lte=paper.id).count()


def paper_display_number_map(papers: list[Paper]) -> dict[int, int]:
    if not papers:
        return {}
    ids = {paper.id for paper in papers}
    return {
        paper_id: index + 1
        for index, paper_id in enumerate(Paper.objects.order_by("id").values_list("id", flat=True))
        if paper_id in ids
    }


class PaperUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    title = serializers.CharField(max_length=500, required=False, allow_blank=True)
    year = serializers.IntegerField(required=False, min_value=1800, max_value=2200)
    venue = serializers.CharField(max_length=180, required=False, allow_blank=True)
    area = serializers.CharField(max_length=160, required=False, allow_blank=True)

    def validate_file(self, value):
        name = value.name.lower()
        if not name.endswith(".pdf"):
            raise serializers.ValidationError("只支持上传 PDF 文件。")
        if value.size > settings.PAPER_UPLOAD_MAX_BYTES:
            limit_mb = settings.PAPER_UPLOAD_MAX_BYTES // (1024 * 1024)
            raise serializers.ValidationError(f"PDF 文件不能超过 {limit_mb} MB。")
        data = value.read()
        value.seek(0)
        if not data.startswith(b"%PDF-"):
            raise serializers.ValidationError("文件内容不是有效的 PDF。")
        try:
            reader = PdfReader(BytesIO(data), strict=False)
            if reader.is_encrypted:
                raise serializers.ValidationError("暂不支持加密 PDF。")
            page_count = len(reader.pages)
        except serializers.ValidationError:
            raise
        except Exception as exc:
            raise serializers.ValidationError("PDF 文件无法解析，请检查文件是否损坏。") from exc
        if page_count > settings.PAPER_UPLOAD_MAX_PAGES:
            raise serializers.ValidationError(f"PDF 页数不能超过 {settings.PAPER_UPLOAD_MAX_PAGES} 页。")
        value.seek(0)
        return value
