from __future__ import annotations

from uuid import uuid4

from django.conf import settings
from django.db import models
from django.utils.text import slugify

from apps.common.permissions import Visibility

from apps.documents.models import Document
from apps.library.models import KnowledgeSpace, TimeStampedModel
from apps.papers.models import Paper


class ExperimentProject(TimeStampedModel):
    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        BLOCKED = "blocked", "Blocked"
        ARCHIVED = "archived", "Archived"

    title = models.CharField(max_length=240)
    visibility = models.CharField(max_length=16, choices=Visibility.choices, default=Visibility.PRIVATE)
    slug = models.SlugField(max_length=260, unique=True, allow_unicode=True)
    paper = models.ForeignKey(Paper, null=True, blank=True, related_name="experiment_projects", on_delete=models.SET_NULL)
    document = models.ForeignKey(Document, null=True, blank=True, related_name="experiment_projects", on_delete=models.SET_NULL)
    space = models.ForeignKey(KnowledgeSpace, null=True, blank=True, related_name="experiment_projects", on_delete=models.SET_NULL)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PLANNED)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="owned_experiment_projects",
        on_delete=models.SET_NULL,
    )
    objective = models.TextField(blank=True)
    protocol_markdown = models.TextField(blank=True)
    repo_url = models.URLField(max_length=500, blank=True)
    environment_json = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at", "title"]

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            base = slugify(self.title, allow_unicode=True)[:220] or "experiment"
            candidate = base
            queryset = ExperimentProject.objects.filter(slug=candidate)
            if self.pk:
                queryset = queryset.exclude(pk=self.pk)
            self.slug = candidate if not queryset.exists() else f"{candidate}-{uuid4().hex[:8]}"
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.title


class ExperimentRun(models.Model):
    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    project = models.ForeignKey(ExperimentProject, related_name="runs", on_delete=models.CASCADE)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PLANNED)
    params_json = models.JSONField(default=dict, blank=True)
    metrics_json = models.JSONField(default=dict, blank=True)
    artifact_keys = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="created_experiment_runs",
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]

    def __str__(self) -> str:
        return f"{self.project_id}:{self.status}"
