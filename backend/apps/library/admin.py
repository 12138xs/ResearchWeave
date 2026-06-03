from __future__ import annotations

from django.contrib import admin

from apps.library.models import Keyword, KnowledgeSpace


@admin.register(Keyword)
class KeywordAdmin(admin.ModelAdmin):
    list_display = ("name", "normalized_name", "updated_at")
    search_fields = ("name", "normalized_name")


@admin.register(KnowledgeSpace)
class KnowledgeSpaceAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "is_active", "order", "updated_at")
    list_filter = ("kind", "is_active")
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}
