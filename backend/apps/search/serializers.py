from __future__ import annotations

from rest_framework import serializers

from apps.search.models import SearchIndexEntry
from apps.tasks.serializers import TaskRecordSerializer


class SearchIndexEntrySerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = SearchIndexEntry
        fields = [
            "id",
            "object_type",
            "object_id",
            "title",
            "summary",
            "space_id",
            "keywords_json",
            "source_updated_at",
            "indexed_at",
            "url",
        ]

    def get_url(self, obj: SearchIndexEntry) -> str:
        if obj.object_type == SearchIndexEntry.ObjectType.PAPER:
            return f"/papers/{obj.object_id}"
        if obj.object_type == SearchIndexEntry.ObjectType.DOCUMENT:
            return f"/docs/{obj.object_id}"
        if obj.object_type == SearchIndexEntry.ObjectType.EXPERIMENT:
            return f"/experiments/{obj.object_id}"
        return "/search"


class SearchReindexResponseSerializer(serializers.Serializer):
    task = TaskRecordSerializer()
