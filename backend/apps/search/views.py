from __future__ import annotations

from rest_framework import generics, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.search.selectors import search_entries
from apps.search.serializers import SearchIndexEntrySerializer
from apps.search.services import enqueue_search_reindex
from apps.tasks.serializers import TaskRecordSerializer


class SearchResultsPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class SearchView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = SearchIndexEntrySerializer
    pagination_class = SearchResultsPagination

    def get_queryset(self):
        return search_entries(self.request.query_params)


class SearchReindexView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        task = enqueue_search_reindex(request.user)
        return Response({"task": TaskRecordSerializer(task).data}, status=status.HTTP_202_ACCEPTED)
