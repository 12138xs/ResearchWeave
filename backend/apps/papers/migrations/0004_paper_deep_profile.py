from __future__ import annotations

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("papers", "0003_paper_light_profile"),
    ]

    operations = [
        migrations.CreateModel(
            name="PaperDeepProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("version", models.PositiveIntegerField(default=1)),
                ("is_active", models.BooleanField(default=True)),
                ("parser_name", models.CharField(default="placeholder_deep_v1", max_length=80)),
                ("summary", models.TextField(blank=True)),
                ("sections", models.JSONField(blank=True, default=list)),
                ("figures", models.JSONField(blank=True, default=list)),
                ("formulas", models.JSONField(blank=True, default=list)),
                ("code_suggestions", models.JSONField(blank=True, default=list)),
                ("reproduction_notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "paper",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="deep_profiles",
                        to="papers.paper",
                    ),
                ),
            ],
            options={"ordering": ["-version", "-created_at"], "unique_together": {("paper", "version")}},
        ),
    ]
