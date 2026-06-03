from __future__ import annotations

from rest_framework.permissions import AllowAny, IsAuthenticated


class ReadOnlyOrAuthenticatedWriteMixin:
    read_methods = {"GET", "HEAD", "OPTIONS"}

    def get_permissions(self):
        if self.request.method in self.read_methods:
            return [AllowAny()]
        return [IsAuthenticated()]
