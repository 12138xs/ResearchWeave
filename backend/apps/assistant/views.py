from __future__ import annotations

import json

from django.http import StreamingHttpResponse
from rest_framework import generics, serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.assistant.models import AssistantExchange, AssistantSession
from apps.assistant.serializers import (
    AssistantExchangeSerializer,
    AssistantMessageInputSerializer,
    AssistantSessionSerializer,
    validate_scope,
)
from apps.assistant.services import control_exchange, create_assistant_exchange


class AssistantSessionListView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AssistantSessionSerializer

    def get_queryset(self):
        return AssistantSession.objects.filter(created_by=self.request.user).prefetch_related("exchanges")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class AssistantSessionDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AssistantSessionSerializer

    def get_queryset(self):
        return AssistantSession.objects.filter(created_by=self.request.user).prefetch_related("exchanges")


class AssistantMessageView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk: int):
        session = generics.get_object_or_404(AssistantSession, pk=pk, created_by=request.user)
        validate_scope(session.scope_json, request.user)
        input_serializer = AssistantMessageInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        exchange = create_assistant_exchange(session, **input_serializer.validated_data)
        return Response(AssistantExchangeSerializer(exchange).data, status=status.HTTP_202_ACCEPTED)


class AssistantExchangeView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, request, pk, exchange_id):
        return generics.get_object_or_404(AssistantExchange.objects.select_related("session__created_by"),
            pk=exchange_id, session_id=pk, session__created_by=request.user)

    def get(self, request, pk, exchange_id):
        exchange = self.get_object(request, pk, exchange_id)
        return Response(AssistantExchangeSerializer(exchange).data)

    def post(self, request, pk, exchange_id):
        exchange = self.get_object(request, pk, exchange_id)
        action, attempt = request.data.get("action"), request.data.get("attempt")
        if action not in ["cancel", "retry"] or type(attempt) is not int or attempt < 1:
            raise serializers.ValidationError("操作或尝试编号不合法。")
        if action == "retry":
            validate_scope(exchange.session.scope_json, request.user)
        exchange = control_exchange(exchange, action, attempt)
        return Response(AssistantExchangeSerializer(exchange).data)


class AssistantProgressView(AssistantExchangeView):
    http_method_names = ["get", "head", "options"]

    def get(self, request, pk, exchange_id):
        exchange = self.get_object(request, pk, exchange_id)
        data = json.dumps(AssistantExchangeSerializer(exchange).data, ensure_ascii=False, default=str)
        # A short snapshot stream releases WSGI threads immediately. EventSource reconnects
        # for the next snapshot; reconnecting is read-only and never dispatches work.
        response = StreamingHttpResponse(iter([f"retry: 2000\nevent: progress\ndata: {data}\n\n"]),
                                         content_type="text/event-stream")
        response["Cache-Control"] = "no-store"
        response["X-Accel-Buffering"] = "no"
        return response
