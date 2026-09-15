from django.conf import settings
from django.db import models

from apps.common.permissions import Visibility
from apps.agent_access.contracts import SourceKind


class ExternalAgentAccess(models.TextChoices):
    BLOCKED = "blocked", "禁止外发"
    APPROVED = "approved", "允许外部 Agent 读取"


class ContentType(models.TextChoices):
    PAPER = "paper", "论文"
    DOCUMENT = "document", "知识文档"
    PROPOSAL = "proposal", "项目申报书"
    EXPERIMENT = "experiment", "实验日志"
    OTHER = "other", "其他 / 待分类"


class Material(models.Model):
    content_type = models.CharField(max_length=16, choices=ContentType.choices, default=ContentType.OTHER, db_default="other", db_index=True)
    # No self-service approval until the disclosure audit workflow is implemented.
    internal_ai_blocked = models.BooleanField(default=False, db_default=False)

    title = models.CharField(max_length=500)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    visibility = models.CharField(max_length=20, choices=Visibility.choices, default=Visibility.TEAM)
    source_kind = models.CharField(max_length=40, choices=SourceKind.choices, default=SourceKind.UNCLASSIFIED)
    external_agent_access = models.CharField(
        max_length=16,
        choices=ExternalAgentAccess.choices,
        default=ExternalAgentAccess.BLOCKED,
        db_index=True,
    )
    external_access_changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="external_material_access_changes",
        on_delete=models.SET_NULL,
    )
    external_access_changed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(external_agent_access=ExternalAgentAccess.BLOCKED)
                    | (
                        ~models.Q(source_kind=SourceKind.UNCLASSIFIED)
                        & models.Q(external_access_changed_by=models.F("owner"))
                        & models.Q(external_access_changed_at__isnull=False)
                    )
                ),
                name="material_external_access_requires_owner_approval",
            ),
        ]


class MaterialVersion(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "等待解析"
        PROCESSING = "processing", "正在解析"
        READY = "ready", "可用"
        REVIEW = "needs_review", "待核对"
        FAILED = "failed", "解析失败"

    material = models.ForeignKey(Material, related_name="versions", on_delete=models.CASCADE)
    number = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64, db_index=True)
    filename = models.CharField(max_length=255)
    format = models.CharField(max_length=10, choices=[("pdf", "PDF"), ("md", "Markdown")])
    storage_key = models.CharField(max_length=500)
    size = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    error = models.TextField(blank=True)
    warnings = models.JSONField(default=list)
    parser_version = models.CharField(max_length=80, blank=True)
    task = models.ForeignKey("tasks.TaskRecord", null=True, on_delete=models.SET_NULL)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-number"]
        constraints = [
            models.UniqueConstraint(fields=["material", "number"], name="material_version_number"),
            models.UniqueConstraint(fields=["material", "sha256"], name="material_version_hash"),
        ]


class Evidence(models.Model):
    version = models.ForeignKey(MaterialVersion, related_name="evidence", on_delete=models.CASCADE)
    ordinal = models.PositiveIntegerField()
    page = models.PositiveIntegerField(null=True)
    line_start = models.PositiveIntegerField(null=True)
    line_end = models.PositiveIntegerField(null=True)
    text = models.TextField(blank=True)
    review_required = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    reviewed_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ["ordinal"]
        constraints = [models.UniqueConstraint(fields=["version", "ordinal"], name="evidence_version_ordinal")]


class ResearchCard(models.Model):
    version = models.ForeignKey(MaterialVersion, related_name="cards", on_delete=models.CASCADE)
    title = models.CharField(max_length=300)
    markdown = models.TextField()
    sha256 = models.CharField(max_length=64)
    evidence = models.ManyToManyField(Evidence)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["version", "sha256"], name="card_version_hash")]


class LegacyPaperLink(models.Model):
    paper = models.ForeignKey("papers.Paper", null=True, on_delete=models.SET_NULL, related_name="material_links")
    version = models.ForeignKey(MaterialVersion, on_delete=models.PROTECT, related_name="legacy_links")
    original_sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["paper", "original_sha256"], name="legacy_paper_original_hash")]
