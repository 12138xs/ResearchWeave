from __future__ import annotations

from django.http import Http404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

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

    def perform_update(self, serializer):
        issue = serializer.instance
        # 保存前按原锚点复核；不承诺此检查与提交之间的原子撤权。
        if not self.get_queryset().filter(
            pk=issue.pk, object_type=issue.object_type, object_id=issue.object_id,
        ).exists():
            raise Http404("No QualityIssue matches the given query.")
        serializer.save()


class QualityAuditEnqueueView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        task = enqueue_quality_audit(request.user)
        return Response({"task": TaskRecordSerializer(task).data}, status=status.HTTP_202_ACCEPTED)
