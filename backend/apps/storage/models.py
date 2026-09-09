from django.conf import settings
from django.db import models

from apps.common.permissions import Visibility


class StoredImage(models.Model):
    filename = models.CharField(max_length=255, unique=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    visibility = models.CharField(max_length=16, choices=Visibility.choices, default=Visibility.TEAM)
    created_at = models.DateTimeField(auto_now_add=True)
