from __future__ import annotations

from django.db import models


class SearchIndexEntry(models.Model):
    class ObjectType(models.TextChoices):
        PAPER = "paper", "Paper"
        DOCUMENT = "document", "Document"
        EXPERIMENT = "experiment", "Experiment"

    object_type = models.CharField(max_length=32, choices=ObjectType.choices)
    object_id = models.PositiveBigIntegerField()
    title = models.CharField(max_length=500)
    summary = models.TextField(blank=True)
    body = models.TextField(blank=True)
    space_id = models.PositiveBigIntegerField(null=True, blank=True)
    keywords_json = models.JSONField(default=list, blank=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    embedding = models.JSONField(null=True, blank=True)
    indexed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["object_type", "title"]
        unique_together = [("object_type", "object_id")]
        indexes = [
            models.Index(fields=["object_type", "object_id"]),
            models.Index(fields=["space_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.object_type}:{self.object_id}:{self.title}"
