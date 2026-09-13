from django.urls import path

from apps.agent_access.views import (
    AgentEvidenceSearchView,
    AgentContextBundleDetailView,
    AgentContextBundleListCreateView,
    AgentMaterialDetailView,
    AgentMaterialListView,
    AgentMeView,
    MaterialExternalAccessView,
    TokenListCreateView,
    TokenRevokeView,
)


urlpatterns = [
    path("me", AgentMeView.as_view(), name="agent-v1-me"),
    path("tokens", TokenListCreateView.as_view(), name="agent-v1-token-list"),
    path("tokens/<uuid:token_id>", TokenRevokeView.as_view(), name="agent-v1-token-revoke"),
    path("materials", AgentMaterialListView.as_view(), name="agent-v1-material-list"),
    path("materials/<int:pk>", AgentMaterialDetailView.as_view(), name="agent-v1-material-detail"),
    path("materials/<int:pk>/external-access", MaterialExternalAccessView.as_view(), name="agent-v1-material-external-access"),
    path("evidence/search", AgentEvidenceSearchView.as_view(), name="agent-v1-evidence-search"),
    path("context-bundles", AgentContextBundleListCreateView.as_view(), name="agent-v1-context-bundle-create"),
    path("context-bundles/<str:bundle_id>", AgentContextBundleDetailView.as_view(), name="agent-v1-context-bundle-detail"),
]
