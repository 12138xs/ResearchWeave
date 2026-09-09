from __future__ import annotations

from django.contrib import admin
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path
import redis

from config.release import load_release_info


def health(request):
    checks = {"django": "ok"}
    with connection.cursor() as cursor:
        cursor.execute("select 1")
        checks["postgres"] = cursor.fetchone()[0]
        cursor.execute("select extname from pg_extension where extname = 'vector'")
        checks["pgvector"] = bool(cursor.fetchone())
    redis_client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
    checks["redis"] = bool(redis_client.ping())
    return JsonResponse({"status": "ok", "checks": checks, "release": load_release_info()})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health),
    path("api/", include("apps.accounts.urls")),
    path("api/", include("apps.library.urls")),
    path("api/", include("apps.papers.urls")),
    path("api/", include("apps.documents.urls")),
    path("api/", include("apps.ai.urls")),
    path("api/", include("apps.storage.urls")),
    path("api/", include("apps.materials.urls")),
    path("api/", include("apps.tasks.urls")),
    path("api/", include("apps.experiments.urls")),
    path("api/", include("apps.search.urls")),
    path("api/", include("apps.quality.urls")),
    path("api/", include("apps.assistant.urls")),
    path("api/", include("apps.research_map.urls")),
]
