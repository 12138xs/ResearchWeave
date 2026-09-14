from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('materials', '0003_source_kind_external_access'), ('papers', '0006_paperreadingstate_readingreview')]
    operations = [migrations.CreateModel(
        name='LegacyPaperLink',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('original_sha256', models.CharField(max_length=64)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('paper', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='material_links', to='papers.paper')),
            ('version', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='legacy_links', to='materials.materialversion')),
        ],
        options={'constraints': [models.UniqueConstraint(fields=('paper', 'original_sha256'), name='legacy_paper_original_hash')]},
    )]
