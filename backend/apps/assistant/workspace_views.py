from django.http import HttpResponse
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError

from apps.assistant.models import PersonalEntry, PersonalProfile, ResearchPublication
from apps.assistant.workspace import publish_entry, save_entry, save_profile
from apps.assistant.workspace_selectors import publication_allowed
from apps.assistant.workspace_serializers import EntrySerializer, ProfileSerializer, PublicationInput, PublicationSerializer


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        row = PersonalProfile.objects.filter(owner=request.user).first() or PersonalProfile(owner=request.user)
        return Response(ProfileSerializer(row).data)

    def patch(self, request):
        serializer = ProfileSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(ProfileSerializer(save_profile(request.user, serializer.validated_data)).data)


class EntryListView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EntrySerializer

    def get_queryset(self):
        return PersonalEntry.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.instance = save_entry(self.request.user, serializer.validated_data)


class EntryDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EntrySerializer

    def get_queryset(self):
        return PersonalEntry.objects.filter(owner=self.request.user)

    def perform_update(self, serializer):
        serializer.instance = save_entry(self.request.user, serializer.validated_data, serializer.instance)


class PublishEntryView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        entry = generics.get_object_or_404(PersonalEntry, pk=pk, owner=request.user, kind="note")
        serializer = PublicationInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = publish_entry(request.user, entry, serializer.validated_data)
        return Response(PublicationSerializer(row, context={"request": request}).data, status=201)


class PublicationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = [row for row in ResearchPublication.objects.all()[:200] if publication_allowed(row)]
        return Response(PublicationSerializer(rows, many=True, context={"request": request}).data)


class PublicationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        row = generics.get_object_or_404(ResearchPublication, pk=pk)
        if not publication_allowed(row):
            from django.http import Http404
            raise Http404
        return Response(PublicationSerializer(row, context={"request": request}).data)

    def delete(self, request, pk):
        generics.get_object_or_404(ResearchPublication, pk=pk, owner=request.user).delete()
        return Response(status=204)


class WorkspaceExportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = PersonalProfile.objects.filter(owner=request.user).first()
        section = request.query_params.get("section", "all")
        if section not in ["all", "style", "memory", "note"]:
            raise ValidationError("导出范围不合法。")
        text = "# 我的研究工作区\n"
        if section in ["all", "style"]:
            text += "\n## Agent 风格\n\n" + (profile.style if profile else "")
        entries = PersonalEntry.objects.filter(owner=request.user)
        if section == "style":
            entries = entries.none()
        elif section != "all":
            entries = entries.filter(kind=section)
        for row in entries:
            text += f"\n\n## {row.title}\n\n类型：{row.kind}；启用：{row.enabled}；状态：{row.status}；来源会话：{row.source_session_id or '手动'}\n\n{row.body}"
        response = HttpResponse(text, content_type="text/markdown; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="my-research-{section}.md"'
        return response
