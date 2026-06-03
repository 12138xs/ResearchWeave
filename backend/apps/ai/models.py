from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.papers.models import Paper


class PaperQAExchange(models.Model):
    paper = models.ForeignKey(Paper, related_name="qa_exchanges", on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="paper_qa_exchanges",
        on_delete=models.SET_NULL,
    )
    question = models.TextField()
    answer = models.TextField()
    mode = models.CharField(max_length=20, default="compressed")
    model = models.CharField(max_length=120, blank=True)
    usage = models.JSONField(default=dict, blank=True)
    sources = models.JSONField(default=list, blank=True)
    context_warning = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.paper_id}:qa:{self.id}"
