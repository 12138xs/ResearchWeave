from __future__ import annotations

from django.db import migrations, models
from django.db.models import Q


def keep_latest_active_deep_profile(apps, schema_editor):
    PaperDeepProfile = apps.get_model("papers", "PaperDeepProfile")
    active_paper_ids = (
        PaperDeepProfile.objects.filter(is_active=True)
        .values_list("paper_id", flat=True)
        .distinct()
    )
    for paper_id in active_paper_ids:
        active_profiles = PaperDeepProfile.objects.filter(paper_id=paper_id, is_active=True).order_by("-version", "-id")
        keeper = active_profiles.first()
        if keeper is None:
            continue
        active_profiles.exclude(pk=keeper.pk).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [
        ("papers", "0004_paper_deep_profile"),
    ]

    operations = [
        migrations.RunPython(keep_latest_active_deep_profile, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="paperdeepprofile",
            constraint=models.UniqueConstraint(
                fields=("paper",),
                condition=Q(is_active=True),
                name="unique_active_deep_profile_per_paper",
            ),
        ),
    ]
