from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="AgentAccessToken",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("name", models.CharField(max_length=120)),
                ("secret_hash", models.CharField(max_length=64)),
                ("scopes", models.JSONField(default=list)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("last_used_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="agent_access_tokens", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at", "-pk"]},
        ),
        migrations.CreateModel(
            name="AgentAuditEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("request_id", models.UUIDField(db_index=True, default=uuid.uuid4)),
                ("client", models.CharField(blank=True, max_length=120)),
                ("action", models.CharField(max_length=120)),
                ("method", models.CharField(max_length=12)),
                ("path", models.CharField(max_length=300)),
                ("status_code", models.PositiveSmallIntegerField()),
                ("error_code", models.CharField(blank=True, max_length=80)),
                ("returned_count", models.PositiveIntegerField(null=True)),
                ("duration_ms", models.PositiveIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("token", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to="agent_access.agentaccesstoken")),
                ("user", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at", "-pk"]},
        ),
    ]
