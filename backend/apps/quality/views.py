from __future__ import annotations

from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.quality.models import QualityIssue
from apps.quality.selectors import quality_issue_queryset
from apps.quality.serializers import QualityIssueSerializer
from apps.quality.services import enqueue_quality_audit
from apps.tasks.serializers import TaskRecordSerializer


class QualityIssueListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = QualityIssueSerializer

    def get_queryset(self):
        return quality_issue_queryset(self.request.query_params, user=self.request.user)


class QualityIssueDetailView(generics.UpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = QualityIssueSerializer
    def get_queryset(self):
        return quality_issue_queryset({}, user=self.request.user, write=True)


class QualityAuditEnqueueView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        task = enqueue_quality_audit(request.user)
        return Response({"task": TaskRecordSerializer(task).data}, status=status.HTTP_202_ACCEPTED)
