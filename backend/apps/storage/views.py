from __future__ import annotations

import mimetypes
from pathlib import Path
from uuid import uuid4

from django.http import FileResponse, Http404
from django.utils.text import slugify
from rest_framework import serializers
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.storage.provider import get_storage_provider


ALLOWED_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class ImageUploadSerializer(serializers.Serializer):
    image = serializers.FileField()

    def validate_image(self, value):
        if value.content_type not in ALLOWED_IMAGE_TYPES:
            raise serializers.ValidationError("只支持 PNG、JPEG、WebP 或 GIF 图片。")
        if value.size > MAX_IMAGE_BYTES:
            raise serializers.ValidationError("图片不能超过 10 MB。")
        return value


class ImageUploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        serializer = ImageUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        image = serializer.validated_data["image"]
        provider = get_storage_provider()
        provider.ensure_runtime_dirs()
        extension = ALLOWED_IMAGE_TYPES[image.content_type]
        safe_name = _safe_image_name(image.name, extension)
        storage_key = f"objects/images/{safe_name}"
        target = provider.resolve(storage_key)
        with target.open("wb") as handle:
            for chunk in image.chunks():
                handle.write(chunk)
        url = f"/api/assets/images/{safe_name}"
        alt = Path(image.name).stem.strip() or "image"
        return Response(
            {
                "url": url,
                "storage_key": storage_key,
                "markdown": f"![{alt}]({url})",
            },
            status=201,
        )


class ImageAssetView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, filename: str):
        if "/" in filename or "\\" in filename or ".." in filename:
            raise Http404("Image not found.")
        storage_key = f"objects/images/{filename}"
        try:
            path = get_storage_provider().resolve(storage_key)
        except ValueError as exc:
            raise Http404("Image not found.") from exc
        if not path.exists() or not path.is_file():
            raise Http404("Image not found.")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(path.open("rb"), content_type=content_type)


def _safe_image_name(filename: str, extension: str) -> str:
    stem = Path(filename).stem
    safe_stem = slugify(stem, allow_unicode=True) or "image"
    return f"{safe_stem[:80]}-{uuid4().hex[:12]}{extension}"
