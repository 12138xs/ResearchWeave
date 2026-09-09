from apps.tasks.models import TaskRecord


def visible_tasks(user):
    if not getattr(user, "is_authenticated", False):
        return TaskRecord.objects.none()
    # Results/errors may contain private inputs. Ownership is stricter than source visibility.
    return TaskRecord.objects.filter(created_by=user)
