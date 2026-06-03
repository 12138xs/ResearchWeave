from __future__ import annotations

from django.urls import path

from apps.assistant.views import AssistantMessageView, AssistantSessionDetailView, AssistantSessionListView


urlpatterns = [
    path("assistant/sessions/", AssistantSessionListView.as_view(), name="assistant-session-list"),
    path("assistant/sessions/<int:pk>/", AssistantSessionDetailView.as_view(), name="assistant-session-detail"),
    path("assistant/sessions/<int:pk>/messages/", AssistantMessageView.as_view(), name="assistant-session-message"),
]
