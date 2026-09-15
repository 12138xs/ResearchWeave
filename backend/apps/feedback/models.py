from django.conf import settings
from django.db import models


class Feedback(models.Model):
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    author_name = models.CharField(max_length=150)
    content = models.TextField(max_length=4000)
    features = models.JSONField(default=list)
    request_id = models.UUIDField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
