from celery import shared_task

from apps.materials.services import parse_version


@shared_task(soft_time_limit=120, time_limit=150)
def parse_material(version_id):
    parse_version(version_id)
