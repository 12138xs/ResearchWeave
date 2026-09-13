from django.contrib import admin

from apps.agent_access.models import AgentAuditEvent


@admin.register(AgentAuditEvent)
class AgentAuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "user", "client", "status_code", "duration_ms")
    list_filter = ("action", "status_code", "created_at")
    search_fields = ("request_id", "client", "path")
    readonly_fields = tuple(field.name for field in AgentAuditEvent._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

