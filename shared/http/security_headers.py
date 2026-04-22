from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse


class RequestHardeningMiddleware:
    """Reject malformed API requests before they reach views."""

    _allowed_content_types = (
        "application/json",
        "application/x-www-form-urlencoded",
        "multipart/form-data",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if "\x00" in (request.path or "") or "\x00" in (request.META.get("QUERY_STRING", "") or ""):
            return JsonResponse({"detail": "Invalid request path."}, status=400)

        if request.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH"}:
            max_bytes = int(getattr(settings, "MAX_REQUEST_BODY_BYTES", 10 * 1024 * 1024))
            try:
                content_length = int(request.META.get("CONTENT_LENGTH") or 0)
            except (TypeError, ValueError):
                content_length = 0
            if content_length > max_bytes:
                return JsonResponse({"detail": "Request body too large."}, status=413)

            content_type = (request.META.get("CONTENT_TYPE") or "").split(";", 1)[0].strip().lower()
            if content_type and content_type not in self._allowed_content_types:
                return JsonResponse({"detail": "Unsupported Content-Type."}, status=415)

        return self.get_response(request)


class SecurityHeadersMiddleware:
    """Apply additional hardened response headers."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)

        if "X-Content-Type-Options" not in response:
            response["X-Content-Type-Options"] = "nosniff"
        if "Referrer-Policy" not in response:
            response["Referrer-Policy"] = getattr(settings, "SECURE_REFERRER_POLICY", "strict-origin-when-cross-origin")
        if "Permissions-Policy" not in response:
            response["Permissions-Policy"] = getattr(
                settings,
                "PERMISSIONS_POLICY_HEADER",
                "geolocation=(), microphone=(), camera=(), payment=(), usb=()",
            )

        csp_value = getattr(settings, "CONTENT_SECURITY_POLICY", "")
        if csp_value:
            csp_header = "Content-Security-Policy-Report-Only" if getattr(settings, "CSP_REPORT_ONLY", False) else "Content-Security-Policy"
            if csp_header not in response:
                response[csp_header] = csp_value

        return response
