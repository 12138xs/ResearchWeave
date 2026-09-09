from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.library.models import KnowledgeSpace
from apps.research_map.selectors import direction_map_payload
from apps.research_map.services import enqueue_direction_map_generation
from apps.tasks.serializers import TaskRecordSerializer


class KnowledgeSpaceMapView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk: int):
        root_space = get_object_or_404(KnowledgeSpace, pk=pk, is_active=True)
        return Response(direction_map_payload(root_space))


class KnowledgeSpaceMapGenerateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk: int):
        root_space = get_object_or_404(KnowledgeSpace, pk=pk, is_active=True)
        task = enqueue_direction_map_generation(root_space, request.user)
        return Response({"task": TaskRecordSerializer(task).data}, status=status.HTTP_202_ACCEPTED)
