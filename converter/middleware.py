from django.http import HttpResponseForbidden


class LocalOnlyMiddleware:
    """This single-user application is deliberately not a hosted service."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.META.get("REMOTE_ADDR") not in ("127.0.0.1", "::1"):
            return HttpResponseForbidden("This application accepts local connections only.")
        response = self.get_response(request)
        response["Referrer-Policy"] = "same-origin"
        response["Cache-Control"] = "no-store"
        response["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
            "object-src 'none'; base-uri 'self'; form-action 'self'"
        )
        return response
