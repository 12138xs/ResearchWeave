from __future__ import annotations

from rest_framework import serializers

from apps.library.models import KnowledgeSpace


class KeywordLibraryEntrySerializer(serializers.Serializer):
    name = serializers.CharField()
    aliases = serializers.ListField(child=serializers.CharField())
    paper_count = serializers.IntegerField()
    document_count = serializers.IntegerField()
    total_count = serializers.IntegerField()
    source = serializers.CharField()


class KnowledgeSpaceSerializer(serializers.ModelSerializer):
    parent_id = serializers.PrimaryKeyRelatedField(
        queryset=KnowledgeSpace.objects.filter(is_active=True),
        source="parent",
        required=False,
        allow_null=True,
    )
    path = serializers.SerializerMethodField()
    depth = serializers.SerializerMethodField()
    descendant_count = serializers.SerializerMethodField()

    class Meta:
        model = KnowledgeSpace
        fields = [
            "id",
            "name",
            "slug",
            "kind",
            "description",
            "parent_id",
            "order",
            "is_active",
            "path",
            "depth",
            "descendant_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "slug",
            "is_active",
            "created_at",
            "updated_at",
            "path",
            "depth",
            "descendant_count",
        ]

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        parent = attrs.get("parent")
        if self.instance and self.instance.would_create_cycle(parent):
            raise serializers.ValidationError(
                {"detail": "Update would create a cycle in the knowledge tree."}
            )
        return attrs

    def get_path(self, obj: KnowledgeSpace) -> str:
        spaces_by_id = self._active_spaces_by_id()
        if spaces_by_id is not None:
            names = [space.name for space in self._cached_ancestors(obj, spaces_by_id)] + [obj.name]
            return " / ".join(names)
        return obj.path_label()

    def get_depth(self, obj: KnowledgeSpace) -> int:
        spaces_by_id = self._active_spaces_by_id()
        if spaces_by_id is not None:
            return len(self._cached_ancestors(obj, spaces_by_id))
        return obj.depth()

    def get_descendant_count(self, obj: KnowledgeSpace) -> int:
        children_by_parent = self._children_by_parent()
        if children_by_parent is not None:
            count = 0
            visited = {obj.id}
            stack = list(children_by_parent.get(obj.id, []))
            while stack:
                child = stack.pop()
                if child.id in visited:
                    continue
                visited.add(child.id)
                count += 1
                stack.extend(children_by_parent.get(child.id, []))
            return count
        return len(obj.descendant_ids())

    def _active_spaces_by_id(self) -> dict[int, KnowledgeSpace] | None:
        if "active_spaces_by_id" in self.context:
            return self.context["active_spaces_by_id"]
        active_spaces = self.context.get("active_spaces")
        if active_spaces is None:
            return None
        spaces_by_id = {space.id: space for space in active_spaces}
        self.context["active_spaces_by_id"] = spaces_by_id
        return spaces_by_id

    def _children_by_parent(self) -> dict[int, list[KnowledgeSpace]] | None:
        if "children_by_parent" in self.context:
            return self.context["children_by_parent"]
        active_spaces = self.context.get("active_spaces")
        if active_spaces is None:
            return None
        children_by_parent: dict[int, list[KnowledgeSpace]] = {}
        for space in active_spaces:
            if space.parent_id is not None:
                children_by_parent.setdefault(space.parent_id, []).append(space)
        self.context["children_by_parent"] = children_by_parent
        return children_by_parent

    def _cached_ancestors(
        self,
        obj: KnowledgeSpace,
        spaces_by_id: dict[int, KnowledgeSpace],
    ) -> list[KnowledgeSpace]:
        items: list[KnowledgeSpace] = []
        visited = {obj.id}
        parent_id = obj.parent_id
        while parent_id is not None:
            if parent_id in visited:
                break
            visited.add(parent_id)
            parent = spaces_by_id.get(parent_id)
            if parent is None:
                break
            items.append(parent)
            parent_id = parent.parent_id
        items.reverse()
        return items
