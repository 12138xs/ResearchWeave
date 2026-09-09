from django.db import models
from django.db.models import Q
from rest_framework.permissions import IsAuthenticated


class Visibility(models.TextChoices):
    PRIVATE = "private", "仅本人"
    TEAM = "team", "团队共享"


def visible_to(queryset, user, *, owner_field="owner"):
    """Do not allow staff privileges to implicitly expose another member's private data."""
    if not getattr(user, "is_authenticated", False):
        return queryset.none()
    return queryset.filter(Q(visibility=Visibility.TEAM) | Q(**{owner_field: user}))


def editable_by(queryset, user, *, owner_field="owner"):
    queryset = visible_to(queryset, user, owner_field=owner_field)
    if getattr(user, "is_staff", False):
        return queryset
    return queryset.filter(**{owner_field: user})


class ReadOnlyOrAuthenticatedWriteMixin:
    # Keep existing imports compatible; workspace reads now require membership too.
    def get_permissions(self):
        return [IsAuthenticated()]
