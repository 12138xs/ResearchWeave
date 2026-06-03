from __future__ import annotations

from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.assistant.models import AssistantSession
from apps.assistant.serializers import (
    AssistantExchangeSerializer,
    AssistantMessageInputSerializer,
    AssistantSessionSerializer,
)
from apps.assistant.services import create_assistant_exchange


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
        input_serializer = AssistantMessageInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        exchange = create_assistant_exchange(session, input_serializer.validated_data["question"])
        return Response(AssistantExchangeSerializer(exchange).data, status=status.HTTP_201_CREATED)
