from __future__ import annotations

from django.urls import path

from apps.assistant.views import AssistantExchangeView, AssistantProgressView, AssistantMessageView, AssistantSessionDetailView, AssistantSessionListView
from apps.assistant.workspace_views import ProfileView, EntryListView, EntryDetailView, PublishEntryView, PublicationListView, PublicationDetailView, WorkspaceExportView


urlpatterns = [
    path("assistant/workspace/profile/", ProfileView.as_view()),
    path("assistant/workspace/entries/", EntryListView.as_view()),
    path("assistant/workspace/entries/<int:pk>/", EntryDetailView.as_view()),
    path("assistant/workspace/entries/<int:pk>/publish/", PublishEntryView.as_view()),
    path("assistant/workspace/export/", WorkspaceExportView.as_view()),
    path("assistant/publications/", PublicationListView.as_view()),
    path("assistant/publications/<int:pk>/", PublicationDetailView.as_view()),
    path("assistant/sessions/<int:pk>/exchanges/<int:exchange_id>/", AssistantExchangeView.as_view(), name="assistant-exchange"),
    path("assistant/sessions/<int:pk>/exchanges/<int:exchange_id>/progress/", AssistantProgressView.as_view(), name="assistant-progress"),
    path("assistant/sessions/", AssistantSessionListView.as_view(), name="assistant-session-list"),
    path("assistant/sessions/<int:pk>/", AssistantSessionDetailView.as_view(), name="assistant-session-detail"),
    path("assistant/sessions/<int:pk>/messages/", AssistantMessageView.as_view(), name="assistant-session-message"),
]
