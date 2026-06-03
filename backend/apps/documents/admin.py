from __future__ import annotations

from django.contrib import admin

from apps.documents.models import Document, DocumentVersion


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "space", "status", "updated_at")
    list_filter = ("status", "space")
    search_fields = ("title", "summary")
    prepopulated_fields = {"slug": ("title",)}
    filter_horizontal = ("keywords",)


@admin.register(DocumentVersion)
class DocumentVersionAdmin(admin.ModelAdmin):
    list_display = ("document", "version", "is_current", "created_at")
    list_filter = ("is_current",)
    search_fields = ("document__title", "markdown")
