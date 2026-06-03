from __future__ import annotations

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("papers", "0002_paper_citation_metadata"),
    ]

    operations = [
        migrations.CreateModel(
            name="PaperLightProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("version", models.PositiveIntegerField(default=1)),
                ("is_active", models.BooleanField(default=True)),
                ("generator", models.CharField(default="rule_based_v1", max_length=80)),
                ("keywords", models.JSONField(blank=True, default=list)),
                ("background", models.TextField(blank=True)),
                ("method", models.TextField(blank=True)),
                ("results", models.TextField(blank=True)),
                ("source_text_preview", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "paper",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="light_profiles",
                        to="papers.paper",
                    ),
                ),
            ],
            options={"ordering": ["-version", "-created_at"], "unique_together": {("paper", "version")}},
        ),
    ]
