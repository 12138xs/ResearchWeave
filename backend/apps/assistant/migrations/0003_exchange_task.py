from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("assistant", "0002_exchange_execution"), ("tasks", "0002_taskrecord_result_object")]
    operations = [migrations.AddField("assistantexchange", "task", models.ForeignKey(
        null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL, to="tasks.taskrecord"))]
