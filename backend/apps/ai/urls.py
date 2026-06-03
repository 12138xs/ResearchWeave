from __future__ import annotations

from django.urls import path

from apps.ai.views import CurrentPaperQAHistoryView, CurrentPaperQAView, PaperQAView

urlpatterns = [
    path("qa/papers/", PaperQAView.as_view(), name="paper-qa"),
    path("qa/papers/<int:pk>/history/", CurrentPaperQAHistoryView.as_view(), name="current-paper-qa-history"),
    path("qa/papers/<int:pk>/", CurrentPaperQAView.as_view(), name="current-paper-qa"),
]
