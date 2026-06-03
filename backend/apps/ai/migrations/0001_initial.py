from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("papers", "0005_unique_active_deep_profile"),
    ]

    operations = [
        migrations.CreateModel(
            name="PaperQAExchange",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("question", models.TextField()),
                ("answer", models.TextField()),
                ("mode", models.CharField(default="compressed", max_length=20)),
                ("model", models.CharField(blank=True, max_length=120)),
                ("usage", models.JSONField(blank=True, default=dict)),
                ("sources", models.JSONField(blank=True, default=list)),
                ("context_warning", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "paper",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="qa_exchanges", to="papers.paper"),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="paper_qa_exchanges",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
    ]
