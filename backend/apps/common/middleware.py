from django.utils.cache import patch_vary_headers


class PrivateAPIResponseMiddleware:
    """User-scoped API responses must not be reused by shared or browser caches."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith("/api/"):
            response["Cache-Control"] = "private, no-store"
            patch_vary_headers(response, ["Cookie", "Authorization"])
        return response
