from django.conf import settings
from django.db import models

from apps.common.permissions import Visibility


class Material(models.Model):
    title = models.CharField(max_length=500)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    visibility = models.CharField(max_length=20, choices=Visibility.choices, default=Visibility.TEAM)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]


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
