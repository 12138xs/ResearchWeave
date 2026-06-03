from __future__ import annotations

from django.contrib import admin

from apps.papers.models import Paper, PaperDeepProfile, PaperLightProfile


@admin.register(Paper)
class PaperAdmin(admin.ModelAdmin):
    list_display = ("title", "year", "publication_type", "venue", "area", "status", "code_status", "updated_at")
    list_filter = ("publication_type", "status", "code_status", "year", "area")
    search_fields = ("title", "authors", "abstract", "doi", "arxiv_id", "venue")
    prepopulated_fields = {"slug": ("title",)}
    filter_horizontal = ("keywords",)


@admin.register(PaperLightProfile)
class PaperLightProfileAdmin(admin.ModelAdmin):
    list_display = ("paper", "version", "is_active", "generator", "created_at")
    list_filter = ("is_active", "generator")
    search_fields = ("paper__title", "background", "method", "results")


@admin.register(PaperDeepProfile)
class PaperDeepProfileAdmin(admin.ModelAdmin):
    list_display = ("paper", "version", "is_active", "parser_name", "created_at")
    list_filter = ("is_active", "parser_name")
    search_fields = ("paper__title", "summary", "reproduction_notes")
