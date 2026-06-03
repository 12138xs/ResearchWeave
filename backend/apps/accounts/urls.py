from __future__ import annotations

from django.urls import path

from apps.accounts.views import LoginView, LogoutView, MeView

urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
    path("auth/login/", LoginView.as_view(), name="auth-login"),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout"),
]
