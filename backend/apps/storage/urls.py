from __future__ import annotations

from django.urls import path

from apps.storage.views import ImageAssetView, ImageUploadView

urlpatterns = [
    path("storage/upload-image/", ImageUploadView.as_view(), name="storage-upload-image"),
    path("assets/images/<str:filename>", ImageAssetView.as_view(), name="image-asset"),
]
