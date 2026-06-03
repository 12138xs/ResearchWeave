from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("papers", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="paper",
            name="authors",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="paper",
            name="publication_type",
            field=models.CharField(
                choices=[
                    ("article", "Journal article"),
                    ("conference", "Conference paper"),
                    ("preprint", "Preprint"),
                    ("thesis", "Thesis"),
                    ("report", "Report"),
                    ("other", "Other"),
                ],
                default="article",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="paper",
            name="volume",
            field=models.CharField(blank=True, max_length=60),
        ),
        migrations.AddField(
            model_name="paper",
            name="issue",
            field=models.CharField(blank=True, max_length=60),
        ),
        migrations.AddField(
            model_name="paper",
            name="pages",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="paper",
            name="source_url",
            field=models.URLField(blank=True, max_length=500),
        ),
    ]
