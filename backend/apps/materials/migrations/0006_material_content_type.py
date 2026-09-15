from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('materials', '0005_legacy_rollback_compatibility')]
    operations = [
        migrations.AddField(model_name='material', name='content_type', field=models.CharField(
            max_length=16, choices=[('paper', '论文'), ('document', '知识文档'), ('proposal', '项目申报书'), ('experiment', '实验日志'), ('other', '其他 / 待分类')],
            default='other', db_default='other', db_index=True)),
        migrations.AddField(model_name='material', name='internal_ai_blocked', field=models.BooleanField(default=False, db_default=False)),
    ]
