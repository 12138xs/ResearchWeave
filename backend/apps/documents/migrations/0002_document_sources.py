from __future__ import annotations

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentSource",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "source_type",
                    models.CharField(
                        choices=[
                            ("url", "URL"),
                            ("markdown_upload", "Markdown Upload"),
                            ("text_upload", "Text Upload"),
                            ("pdf", "PDF"),
                            ("manual", "Manual"),
                            ("llm_draft", "LLM Draft"),
                        ],
                        max_length=40,
                    ),
                ),
                ("title", models.CharField(blank=True, max_length=260)),
                ("url", models.URLField(blank=True)),
                ("storage_key", models.CharField(blank=True, max_length=500)),
                ("content_hash", models.CharField(blank=True, max_length=128)),
                ("raw_excerpt", models.TextField(blank=True)),
                ("license_note", models.TextField(blank=True)),
                ("attribution", models.TextField(blank=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "document",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="sources",
                        to="documents.document",
                    ),
                ),
            ],
            options={"ordering": ["-created_at", "id"]},
        ),
    ]
