from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskrecord",
            name="object_type",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="taskrecord",
            name="object_id",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="taskrecord",
            name="result",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
