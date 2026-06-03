from __future__ import annotations

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0002_document_sources"),
        ("library", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentImportBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=240)),
                (
                    "source_mode",
                    models.CharField(
                        choices=[
                            ("urls", "URLs"),
                            ("files", "Files"),
                            ("pasted_text", "Pasted Text"),
                            ("mixed", "Mixed"),
                        ],
                        max_length=40,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("queued", "Queued"),
                            ("processing", "Processing"),
                            ("needs_review", "Needs Review"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="draft",
                        max_length=40,
                    ),
                ),
                ("options_json", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
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
                    "sources",
                    models.ManyToManyField(
                        blank=True,
                        related_name="import_batches",
                        to="documents.documentsource",
                    ),
                ),
                (
                    "target_space",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="document_import_batches",
                        to="library.knowledgespace",
                    ),
                ),
            ],
            options={"ordering": ["-created_at", "id"]},
        ),
        migrations.CreateModel(
            name="DocumentImportCandidate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("proposed_title", models.CharField(max_length=240)),
                ("proposed_summary", models.TextField(blank=True)),
                ("proposed_markdown", models.TextField(blank=True)),
                ("proposed_keywords", models.JSONField(blank=True, default=list)),
                ("quality_notes", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("needs_review", "Needs Review"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                            ("imported", "Imported"),
                        ],
                        default="draft",
                        max_length=40,
                    ),
                ),
                ("confidence", models.FloatField(default=0.0)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="candidates",
                        to="documents.documentimportbatch",
                    ),
                ),
                (
                    "document",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="import_candidates",
                        to="documents.document",
                    ),
                ),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reviewed_document_import_candidates",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "source",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="import_candidates",
                        to="documents.documentsource",
                    ),
                ),
                (
                    "target_space",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="document_import_candidates",
                        to="library.knowledgespace",
                    ),
                ),
            ],
            options={"ordering": ["-created_at", "id"]},
        ),
    ]
