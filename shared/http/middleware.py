from __future__ import annotations

import re
import time
import uuid
from typing import Callable

from django.http import HttpRequest, HttpResponse

from shared.http.context import reset_request_id, reset_user_id, set_request_id, set_user_id


_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class RequestContextMiddleware:
    """Attach a request id to every request and propagate it to responses.

    - Uses inbound `X-Request-ID` if present and well-formed.
    - Otherwise generates a UUID4.
    - Stores `request.request_id` for request-scoped logging.
    """

    header_name = "HTTP_X_REQUEST_ID"
    response_header = "X-Request-ID"

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        inbound = (request.META.get(self.header_name) or "").strip()
        request_id = inbound if inbound and _REQUEST_ID_RE.match(inbound) else uuid.uuid4().hex

        request.request_id = request_id
        request_id_token = set_request_id(request_id)

        user_id_token = None
        try:
            user = getattr(request, "user", None)
            if user is not None and getattr(user, "is_authenticated", False):
                user_id_token = set_user_id(str(getattr(user, "id", "")) or None)

            response = self.get_response(request)
        finally:
            reset_request_id(request_id_token)
            if user_id_token is not None:
                reset_user_id(user_id_token)

        response[self.response_header] = request_id
        return response


class RequestLoggingMiddleware:
    """Structured request logging with request id propagation.

    This middleware logs a single line per request with safe, high-signal
    fields (no request/response bodies).
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        import logging

        logger = logging.getLogger("builder.request")
        start = time.monotonic()
        response: HttpResponse | None = None
        exc: BaseException | None = None

        try:
            response = self.get_response(request)
            return response
        except BaseException as caught:
            exc = caught
            raise
        finally:
            duration_ms = int((time.monotonic() - start) * 1000)
            path = getattr(request, "path", "") or ""
            should_log = not path.startswith(("/api/health", "/api/ready", "/api/live"))

            user = getattr(request, "user", None)
            user_id = None
            if user is not None and getattr(user, "is_authenticated", False):
                user_id = getattr(user, "id", None)

            extra = {
                "request_id": getattr(request, "request_id", None),
                "method": getattr(request, "method", None),
                "path": path,
                "status_code": getattr(response, "status_code", None),
                "duration_ms": duration_ms,
                "user_id": user_id,
            }

            if exc is None:
                if should_log:
                    logger.info("request", extra=extra)
            else:
                if should_log:
                    logger.error("request_failed", extra=extra, exc_info=exc)
