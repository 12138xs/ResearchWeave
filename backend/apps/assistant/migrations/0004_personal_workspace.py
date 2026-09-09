from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("assistant", "0003_exchange_task"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField("assistantexchange", "context_digest", models.CharField(max_length=64, blank=True)),
        migrations.CreateModel(name="PersonalProfile", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("style", models.TextField(blank=True)), ("memory_enabled", models.BooleanField(default=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
            ("owner", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
        ]),
        migrations.CreateModel(name="PersonalEntry", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("kind", models.CharField(max_length=16, choices=[("memory", "个人记忆"), ("note", "实验记录")])),
            ("title", models.CharField(max_length=240)), ("body", models.TextField()),
            ("enabled", models.BooleanField(default=True)),
            ("status", models.CharField(max_length=16, default="planned", choices=[("planned", "计划"), ("observed", "观察"), ("concluded", "结论")])),
            ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ("source_session", models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL, to="assistant.assistantsession")),
        ], options={"ordering": ["-updated_at", "-pk"]}),
        migrations.CreateModel(name="ResearchPublication", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("title", models.CharField(max_length=240)), ("body", models.TextField()),
            ("evidence_ids", models.JSONField(default=list)), ("request_id", models.UUIDField()),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ("source_entry", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to="assistant.personalentry")),
        ], options={"ordering": ["-pk"], "constraints": [models.UniqueConstraint(fields=("owner", "request_id"), name="assistant_publication_once")]}),
    ]
