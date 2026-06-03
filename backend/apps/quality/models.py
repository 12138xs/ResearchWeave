from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.tasks.models import TaskRecord


class QualityIssue(models.Model):
    class Dimension(models.TextChoices):
        METADATA = "metadata", "Metadata"
        AI_OUTPUT = "ai_output", "AI output"
        REPRODUCTION = "reproduction", "Reproduction"
        DOCUMENT = "document", "Document"
        SEARCH_INDEX = "search_index", "Search index"

    class Severity(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        RESOLVED = "resolved", "Resolved"
        DISMISSED = "dismissed", "Dismissed"

    object_type = models.CharField(max_length=80)
    object_id = models.PositiveBigIntegerField()
    dimension = models.CharField(max_length=40, choices=Dimension.choices)
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.MEDIUM)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.OPEN)
    score = models.FloatField(null=True, blank=True)
    notes = models.TextField(blank=True)
    evidence_json = models.JSONField(default=dict, blank=True)
    source_task = models.ForeignKey(TaskRecord, null=True, blank=True, related_name="quality_issues", on_delete=models.SET_NULL)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["object_type", "object_id"]),
            models.Index(fields=["status", "severity"]),
        ]

    def __str__(self) -> str:
        return f"{self.object_type}:{self.object_id}:{self.dimension}:{self.status}"
