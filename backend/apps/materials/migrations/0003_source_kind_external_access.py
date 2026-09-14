from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("materials", "0002_evidence_review"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="material",
            name="source_kind",
            field=models.CharField(
                choices=[
                    ("unclassified", "未分类"),
                    ("paper_fulltext", "论文原文"),
                    ("paper_abstract", "论文摘要"),
                    ("human_record", "人工记录"),
                    ("derived_research_card", "衍生整理卡"),
                    ("agent_summary", "Agent 摘要"),
                    ("experiment_plan", "实验计划"),
                    ("experiment_observation", "实验观察"),
                    ("experiment_interpretation", "实验解释"),
                    ("code_reference", "代码引用"),
                ],
                default="unclassified",
                max_length=40,
            ),
        ),
        migrations.AddField(
            model_name="material",
            name="external_agent_access",
            field=models.CharField(
                choices=[("blocked", "禁止外发"), ("approved", "允许外部 Agent 读取")],
                db_index=True,
                default="blocked",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="material",
            name="external_access_changed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="material",
            name="external_access_changed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="external_material_access_changes",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddConstraint(
            model_name="material",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("external_agent_access", "blocked"))
                    | (
                        ~models.Q(("source_kind", "unclassified"))
                        & models.Q(("external_access_changed_by", models.F("owner")))
                        & models.Q(("external_access_changed_at__isnull", False))
                    )
                ),
                name="material_external_access_requires_owner_approval",
            ),
        ),
    ]
