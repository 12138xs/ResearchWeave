from __future__ import annotations

from uuid import uuid4

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.text import slugify

from apps.library.models import Keyword, KnowledgeSpace, TimeStampedModel


class Paper(TimeStampedModel):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        PARSING = "parsing", "Parsing"
        LIGHT_PROCESSING = "light_processing", "Light processing"
        LIGHT_READY = "light_ready", "Light ready"
        DEEP_PROCESSING = "deep_processing", "Deep processing"
        DEEP_READY = "deep_ready", "Deep ready"
        NEEDS_REVIEW = "needs_review", "Needs review"
        FAILED = "failed", "Failed"
        ARCHIVED = "archived", "Archived"

    class CodeStatus(models.TextChoices):
        MISSING = "missing", "Missing"
        OFFICIAL = "official", "Official"
        INTERNAL = "internal", "Internal"
        BOTH = "both", "Both"

    class PublicationType(models.TextChoices):
        ARTICLE = "article", "Journal article"
        CONFERENCE = "conference", "Conference paper"
        PREPRINT = "preprint", "Preprint"
        THESIS = "thesis", "Thesis"
        REPORT = "report", "Report"
        OTHER = "other", "Other"

    title = models.CharField(max_length=500)
    slug = models.SlugField(max_length=220, unique=True, allow_unicode=True)
    authors = models.JSONField(default=list, blank=True)
    publication_type = models.CharField(
        max_length=24,
        choices=PublicationType.choices,
        default=PublicationType.ARTICLE,
    )
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    venue = models.CharField(max_length=180, blank=True)
    volume = models.CharField(max_length=60, blank=True)
    issue = models.CharField(max_length=60, blank=True)
    pages = models.CharField(max_length=80, blank=True)
    area = models.CharField(max_length=160, blank=True)
    abstract = models.TextField(blank=True)
    doi = models.CharField(max_length=160, blank=True)
    arxiv_id = models.CharField(max_length=80, blank=True)
    source_url = models.URLField(max_length=500, blank=True)
    source_pdf_path = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.UPLOADED)
    code_status = models.CharField(
        max_length=20,
        choices=CodeStatus.choices,
        default=CodeStatus.MISSING,
    )
    space = models.ForeignKey(
        KnowledgeSpace,
        null=True,
        blank=True,
        related_name="papers",
        on_delete=models.SET_NULL,
    )
    keywords = models.ManyToManyField(Keyword, blank=True, related_name="papers")

    class Meta:
        ordering = ["-updated_at", "-year", "title"]

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            base = slugify(self.title, allow_unicode=True)[:180] or "paper"
            suffix = f"-{self.year}" if self.year else ""
            candidate = f"{base}{suffix}"
            queryset = Paper.objects.filter(slug=candidate)
            if self.pk:
                queryset = queryset.exclude(pk=self.pk)
            self.slug = candidate if not queryset.exists() else f"{candidate}-{uuid4().hex[:8]}"
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.title


class PaperLightProfile(models.Model):
    paper = models.ForeignKey(Paper, related_name="light_profiles", on_delete=models.CASCADE)
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    generator = models.CharField(max_length=80, default="rule_based_v1")
    keywords = models.JSONField(default=list, blank=True)
    background = models.TextField(blank=True)
    method = models.TextField(blank=True)
    results = models.TextField(blank=True)
    source_text_preview = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version", "-created_at"]
        unique_together = [("paper", "version")]

    def __str__(self) -> str:
        return f"{self.paper_id}:light:v{self.version}"


class PaperDeepProfile(models.Model):
    paper = models.ForeignKey(Paper, related_name="deep_profiles", on_delete=models.CASCADE)
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    parser_name = models.CharField(max_length=80, default="placeholder_deep_v1")
    summary = models.TextField(blank=True)
    sections = models.JSONField(default=list, blank=True)
    figures = models.JSONField(default=list, blank=True)
    formulas = models.JSONField(default=list, blank=True)
    code_suggestions = models.JSONField(default=list, blank=True)
    reproduction_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version", "-created_at"]
        unique_together = [("paper", "version")]
        constraints = [
            models.UniqueConstraint(
                fields=["paper"],
                condition=Q(is_active=True),
                name="unique_active_deep_profile_per_paper",
            )
        ]

    def __str__(self) -> str:
        return f"{self.paper_id}:deep:v{self.version}"


class PaperReadingState(TimeStampedModel):
    class ReadingStatus(models.TextChoices):
        UNREAD = "unread", "Unread"
        SKIMMED = "skimmed", "Skimmed"
        DEEP_READING = "deep_reading", "Deep reading"
        DISCUSSED = "discussed", "Discussed"
        ADOPTED = "adopted", "Adopted"
        REJECTED = "rejected", "Rejected"

    class ReproductionStatus(models.TextChoices):
        UNKNOWN = "unknown", "Unknown"
        NOT_APPLICABLE = "not_applicable", "Not applicable"
        PLANNED = "planned", "Planned"
        IN_PROGRESS = "in_progress", "In progress"
        REPRODUCED = "reproduced", "Reproduced"
        FAILED = "failed", "Failed"

    paper = models.OneToOneField(Paper, related_name="reading_state", on_delete=models.CASCADE)
    reading_status = models.CharField(
        max_length=32,
        choices=ReadingStatus.choices,
        default=ReadingStatus.UNREAD,
    )
    reproduction_status = models.CharField(
        max_length=32,
        choices=ReproductionStatus.choices,
        default=ReproductionStatus.UNKNOWN,
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="owned_paper_reading_states",
        on_delete=models.SET_NULL,
    )
    next_step = models.TextField(blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="updated_paper_reading_states",
        on_delete=models.SET_NULL,
    )

    class Meta:
        ordering = ["-updated_at", "paper_id"]

    def __str__(self) -> str:
        return f"{self.paper_id}:{self.reading_status}/{self.reproduction_status}"


class ReadingReview(models.Model):
    class ProfileType(models.TextChoices):
        LIGHT = "light", "Light"
        DEEP = "deep", "Deep"

    class Status(models.TextChoices):
        NEEDS_REVIEW = "needs_review", "Needs review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    paper = models.ForeignKey(Paper, related_name="reading_reviews", on_delete=models.CASCADE)
    profile_type = models.CharField(max_length=16, choices=ProfileType.choices)
    profile_id = models.PositiveBigIntegerField()
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.NEEDS_REVIEW)
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="paper_reading_reviews",
        on_delete=models.SET_NULL,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["paper", "profile_type", "profile_id"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"{self.paper_id}:{self.profile_type}:{self.profile_id}:{self.status}"
