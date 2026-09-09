from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):
    dependencies = [("assistant", "0001_initial")]
    operations = [
        migrations.AddField("assistantexchange", "request_id", models.UUIDField(null=True, blank=True)),
        migrations.AddField("assistantexchange", "status", models.CharField(max_length=20, default="completed")),
        migrations.AddField("assistantexchange", "attempt", models.PositiveIntegerField(default=1)),
        migrations.AddField("assistantexchange", "progress", models.CharField(max_length=240, blank=True)),
        migrations.AddField("assistantexchange", "error", models.TextField(blank=True)),
        migrations.AddField("assistantexchange", "updated_at", models.DateTimeField(auto_now=True, default=timezone.now), preserve_default=False),
        migrations.AddConstraint("assistantexchange", models.UniqueConstraint(fields=("session", "request_id"), name="assistant_request_once")),
    ]
