from __future__ import annotations

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("library", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Paper",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("title", models.CharField(max_length=500)),
                ("slug", models.SlugField(allow_unicode=True, max_length=220, unique=True)),
                ("year", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("venue", models.CharField(blank=True, max_length=180)),
                ("area", models.CharField(blank=True, max_length=160)),
                ("abstract", models.TextField(blank=True)),
                ("doi", models.CharField(blank=True, max_length=160)),
                ("arxiv_id", models.CharField(blank=True, max_length=80)),
                ("source_pdf_path", models.CharField(blank=True, max_length=500)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("uploaded", "Uploaded"),
                            ("parsing", "Parsing"),
                            ("light_processing", "Light processing"),
                            ("light_ready", "Light ready"),
                            ("deep_processing", "Deep processing"),
                            ("deep_ready", "Deep ready"),
                            ("needs_review", "Needs review"),
                            ("failed", "Failed"),
                            ("archived", "Archived"),
                        ],
                        default="uploaded",
                        max_length=32,
                    ),
                ),
                (
                    "code_status",
                    models.CharField(
                        choices=[
                            ("missing", "Missing"),
                            ("official", "Official"),
                            ("internal", "Internal"),
                            ("both", "Both"),
                        ],
                        default="missing",
                        max_length=20,
                    ),
                ),
                (
                    "keywords",
                    models.ManyToManyField(blank=True, related_name="papers", to="library.keyword"),
                ),
                (
                    "space",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="papers",
                        to="library.knowledgespace",
                    ),
                ),
            ],
            options={"ordering": ["-updated_at", "-year", "title"]},
        ),
    ]
