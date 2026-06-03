from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.text import slugify

from apps.library.models import Keyword, KnowledgeSpace, TimeStampedModel


class Document(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    title = models.CharField(max_length=240)
    slug = models.SlugField(max_length=260, unique=True, allow_unicode=True)
    summary = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    space = models.ForeignKey(
        KnowledgeSpace,
        null=True,
        blank=True,
        related_name="documents",
        on_delete=models.SET_NULL,
    )
    keywords = models.ManyToManyField(Keyword, blank=True, related_name="documents")

    class Meta:
        ordering = ["-updated_at", "title"]

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = slugify(self.title, allow_unicode=True) or self.title.strip().lower().replace(" ", "-")
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.title


class DocumentVersion(models.Model):
    document = models.ForeignKey(Document, related_name="versions", on_delete=models.CASCADE)
    version = models.PositiveIntegerField(default=1)
    markdown = models.TextField(blank=True)
    is_current = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        unique_together = [("document", "version")]

    def __str__(self) -> str:
        return f"{self.document_id}@v{self.version}"


class DocumentSource(TimeStampedModel):
    class SourceType(models.TextChoices):
        URL = "url", "URL"
        MARKDOWN_UPLOAD = "markdown_upload", "Markdown Upload"
        TEXT_UPLOAD = "text_upload", "Text Upload"
        PDF = "pdf", "PDF"
        MANUAL = "manual", "Manual"
        LLM_DRAFT = "llm_draft", "LLM Draft"

    document = models.ForeignKey(
        Document,
        null=True,
        blank=True,
        related_name="sources",
        on_delete=models.SET_NULL,
    )
    source_type = models.CharField(max_length=40, choices=SourceType.choices)
    title = models.CharField(max_length=260, blank=True)
    url = models.URLField(blank=True)
    storage_key = models.CharField(max_length=500, blank=True)
    content_hash = models.CharField(max_length=128, blank=True)
    raw_excerpt = models.TextField(blank=True)
    license_note = models.TextField(blank=True)
    attribution = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    class Meta:
        ordering = ["-created_at", "id"]

    def __str__(self) -> str:
        return self.title or self.url or self.source_type


class DocumentImportBatch(TimeStampedModel):
    class SourceMode(models.TextChoices):
        URLS = "urls", "URLs"
        FILES = "files", "Files"
        PASTED_TEXT = "pasted_text", "Pasted Text"
        MIXED = "mixed", "Mixed"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        QUEUED = "queued", "Queued"
        PROCESSING = "processing", "Processing"
        NEEDS_REVIEW = "needs_review", "Needs Review"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    name = models.CharField(max_length=240)
    source_mode = models.CharField(max_length=40, choices=SourceMode.choices)
    target_space = models.ForeignKey(
        KnowledgeSpace,
        null=True,
        blank=True,
        related_name="document_import_batches",
        on_delete=models.SET_NULL,
    )
    sources = models.ManyToManyField(DocumentSource, blank=True, related_name="import_batches")
    status = models.CharField(max_length=40, choices=Status.choices, default=Status.DRAFT)
    options_json = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    class Meta:
        ordering = ["-created_at", "id"]

    def __str__(self) -> str:
        return self.name


class DocumentImportCandidate(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        NEEDS_REVIEW = "needs_review", "Needs Review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        IMPORTED = "imported", "Imported"

    batch = models.ForeignKey(DocumentImportBatch, related_name="candidates", on_delete=models.CASCADE)
    source = models.ForeignKey(
        DocumentSource,
        null=True,
        blank=True,
        related_name="import_candidates",
        on_delete=models.SET_NULL,
    )
    target_space = models.ForeignKey(
        KnowledgeSpace,
        null=True,
        blank=True,
        related_name="document_import_candidates",
        on_delete=models.SET_NULL,
    )
    proposed_title = models.CharField(max_length=240)
    proposed_summary = models.TextField(blank=True)
    proposed_markdown = models.TextField(blank=True)
    proposed_keywords = models.JSONField(default=list, blank=True)
    quality_notes = models.TextField(blank=True)
    status = models.CharField(max_length=40, choices=Status.choices, default=Status.DRAFT)
    confidence = models.FloatField(default=0.0)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="reviewed_document_import_candidates",
        on_delete=models.SET_NULL,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    document = models.ForeignKey(
        Document,
        null=True,
        blank=True,
        related_name="import_candidates",
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "id"]

    def __str__(self) -> str:
        return self.proposed_title
