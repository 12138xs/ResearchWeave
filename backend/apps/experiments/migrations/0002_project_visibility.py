from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("experiments", "0001_initial")]

    operations = [
        # Historical projects were shared; preserve that while making new ones private.
        migrations.AddField(
            model_name="experimentproject", name="visibility",
            field=models.CharField(max_length=16, choices=[("private", "仅本人"), ("team", "团队共享")], default="team"),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="experimentproject", name="visibility",
            field=models.CharField(max_length=16, choices=[("private", "仅本人"), ("team", "团队共享")], default="private"),
        ),
    ]
