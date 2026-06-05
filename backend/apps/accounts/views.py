from __future__ import annotations

from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.serializers import session_payload


class MeView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        payload = session_payload(request.user)
        payload["csrf_token"] = get_token(request)
        return Response(payload)


@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        username = str(request.data.get("username", "")).strip()
        password = str(request.data.get("password", ""))
        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response(
                {
                    "authenticated": False,
                    "user": None,
                    "detail": "Invalid username or password.",
                },
                status=400,
            )
        login(request, user)
        payload = session_payload(user)
        payload["csrf_token"] = get_token(request)
        return Response(payload)


@method_decorator(csrf_protect, name="dispatch")
class LogoutView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        logout(request)
        return Response({"authenticated": False, "user": None})
