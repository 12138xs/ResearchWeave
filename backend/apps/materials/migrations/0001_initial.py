from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL), ("tasks", "0001_initial")]
    operations = [
        migrations.CreateModel(name="Material", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("title", models.CharField(max_length=500)),
            ("visibility", models.CharField(choices=[("private", "仅本人"), ("team", "团队共享")], default="team", max_length=20)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("owner", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
        ], options={"ordering": ["-id"]}),
        migrations.CreateModel(name="MaterialVersion", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("number", models.PositiveIntegerField()),
            ("sha256", models.CharField(db_index=True, max_length=64)),
            ("filename", models.CharField(max_length=255)),
            ("format", models.CharField(choices=[("pdf", "PDF"), ("md", "Markdown")], max_length=10)),
            ("storage_key", models.CharField(max_length=500)),
            ("size", models.PositiveIntegerField()),
            ("status", models.CharField(choices=[("queued", "等待解析"), ("processing", "正在解析"), ("ready", "可用"), ("needs_review", "待核对"), ("failed", "解析失败")], default="queued", max_length=20)),
            ("error", models.TextField(blank=True)),
            ("warnings", models.JSONField(default=list)),
            ("parser_version", models.CharField(blank=True, max_length=80)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
            ("material", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="versions", to="materials.material")),
            ("task", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to="tasks.taskrecord")),
            ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
        ], options={"ordering": ["-number"], "constraints": [
            models.UniqueConstraint(fields=("material", "number"), name="material_version_number"),
            models.UniqueConstraint(fields=("material", "sha256"), name="material_version_hash"),
        ]}),
        migrations.CreateModel(name="Evidence", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("ordinal", models.PositiveIntegerField()),
            ("page", models.PositiveIntegerField(null=True)),
            ("line_start", models.PositiveIntegerField(null=True)),
            ("line_end", models.PositiveIntegerField(null=True)),
            ("text", models.TextField(blank=True)),
            ("review_required", models.BooleanField(default=False)),
            ("version", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="evidence", to="materials.materialversion")),
        ], options={"ordering": ["ordinal"], "constraints": [models.UniqueConstraint(fields=("version", "ordinal"), name="evidence_version_ordinal")]}),
        migrations.CreateModel(name="ResearchCard", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("title", models.CharField(max_length=300)),
            ("markdown", models.TextField()),
            ("sha256", models.CharField(max_length=64)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("version", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="cards", to="materials.materialversion")),
            ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ("evidence", models.ManyToManyField(to="materials.evidence")),
        ], options={"constraints": [models.UniqueConstraint(fields=("version", "sha256"), name="card_version_hash")]}),
    ]
