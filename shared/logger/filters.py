from __future__ import annotations

import logging

from shared.http.context import get_request_id, get_user_id


class RequestContextFilter(logging.Filter):
    """Inject request context (request id, user id) into log records."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.request_id = getattr(record, "request_id", None) or get_request_id()
        record.user_id = getattr(record, "user_id", None) or get_user_id()
        return True

