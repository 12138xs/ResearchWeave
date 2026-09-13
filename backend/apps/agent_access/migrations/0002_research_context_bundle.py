from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import apps.agent_access.models


class Migration(migrations.Migration):
    dependencies = [
        ("agent_access", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="ResearchContextBundle",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("bundle_id", models.CharField(default=apps.agent_access.models.new_context_bundle_id, editable=False, max_length=36, unique=True)),
                ("schema_version", models.CharField(default="1.0", max_length=16)),
                ("question", models.TextField()),
                ("scope_json", models.JSONField(default=dict)),
                ("retrieval_manifest", models.JSONField(default=dict)),
                ("evidence_manifest", models.JSONField(default=list)),
                ("missing_information", models.JSONField(default=list)),
                ("warnings", models.JSONField(default=list)),
                ("content_digest", models.CharField(max_length=71)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by_token", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to="agent_access.agentaccesstoken")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="research_context_bundles", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at", "-pk"]},
        ),
    ]
