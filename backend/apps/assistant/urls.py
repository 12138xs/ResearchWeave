from __future__ import annotations

from django.urls import path

from apps.assistant.views import AssistantExchangeView, AssistantProgressView, AssistantMessageView, AssistantSessionDetailView, AssistantSessionListView


urlpatterns = [
    path("assistant/sessions/<int:pk>/exchanges/<int:exchange_id>/", AssistantExchangeView.as_view(), name="assistant-exchange"),
    path("assistant/sessions/<int:pk>/exchanges/<int:exchange_id>/progress/", AssistantProgressView.as_view(), name="assistant-progress"),
    path("assistant/sessions/", AssistantSessionListView.as_view(), name="assistant-session-list"),
    path("assistant/sessions/<int:pk>/", AssistantSessionDetailView.as_view(), name="assistant-session-detail"),
    path("assistant/sessions/<int:pk>/messages/", AssistantMessageView.as_view(), name="assistant-session-message"),
]
