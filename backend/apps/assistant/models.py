from __future__ import annotations

from django.conf import settings
from django.db import models


class AssistantSession(models.Model):
    class Mode(models.TextChoices):
        COMPARE = "compare", "Compare"
        REPRODUCTION_CHECKLIST = "reproduction_checklist", "Reproduction checklist"
        LITERATURE_BRIEF = "literature_brief", "Literature brief"
        FREEFORM_SCOPED = "freeform_scoped", "Freeform scoped"

    title = models.CharField(max_length=240)
    mode = models.CharField(max_length=40, choices=Mode.choices, default=Mode.FREEFORM_SCOPED)
    scope_json = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]

    def __str__(self) -> str:
        return self.title


class AssistantExchange(models.Model):
    session = models.ForeignKey(AssistantSession, related_name="exchanges", on_delete=models.CASCADE)
    question = models.TextField()
    answer = models.TextField(blank=True)
    sources = models.JSONField(default=list, blank=True)
    model = models.CharField(max_length=120, blank=True)
    usage = models.JSONField(default=dict, blank=True)
    context_warning = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    request_id = models.UUIDField(null=True, blank=True)
    task = models.ForeignKey("tasks.TaskRecord", null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=20, default="completed")
    attempt = models.PositiveIntegerField(default=1)
    progress = models.CharField(max_length=240, blank=True)
    error = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [models.UniqueConstraint(fields=["session", "request_id"], name="assistant_request_once")]

    def __str__(self) -> str:
        return f"{self.session_id}:{self.question[:60]}"
