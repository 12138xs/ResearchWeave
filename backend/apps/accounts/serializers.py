from __future__ import annotations

from django.contrib.auth.models import AnonymousUser


def user_payload(user) -> dict[str, object] | None:
    if isinstance(user, AnonymousUser) or not getattr(user, "is_authenticated", False):
        return None
    return {
        "id": user.id,
        "username": user.get_username(),
        "email": user.email,
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
    }


def session_payload(user) -> dict[str, object]:
    payload = user_payload(user)
    return {
        "authenticated": payload is not None,
        "user": payload,
    }
