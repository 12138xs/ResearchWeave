from __future__ import annotations

from django.urls import path

from apps.research_map.views import KnowledgeSpaceMapGenerateView, KnowledgeSpaceMapView


urlpatterns = [
    path("knowledge-spaces/<int:pk>/map/", KnowledgeSpaceMapView.as_view(), name="knowledge-space-map"),
    path("knowledge-spaces/<int:pk>/map/generate/", KnowledgeSpaceMapGenerateView.as_view(), name="knowledge-space-map-generate"),
]
