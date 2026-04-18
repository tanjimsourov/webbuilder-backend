"""
Structured logging configuration for production.
"""

import json
import logging
import traceback
from datetime import datetime

SENSITIVE_FIELD_MARKERS = {
    "password",
    "secret",
    "token",
    "authorization",
    "api_key",
    "private_key",
    "session",
    "cookie",
    "signature",
}


def _redact_sensitive(value, key: str | None = None):
    key_lower = (key or "").lower()
    if key_lower and any(marker in key_lower for marker in SENSITIVE_FIELD_MARKERS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: _redact_sensitive(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_sensitive(item, key) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    """
    JSON formatter for structured logging in production environments.
    Outputs logs in a format suitable for log aggregation systems like
    ELK Stack, CloudWatch, Datadog, etc.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": traceback.format_exception(*record.exc_info) if record.exc_info[0] else None,
            }

        # Add extra fields from the record
        extra_fields = {}
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "exc_info", "exc_text", "thread", "threadName",
                "message", "asctime",
            ):
                try:
                    json.dumps(value)  # Check if serializable
                    extra_fields[key] = value
                except (TypeError, ValueError):
                    extra_fields[key] = str(value)

        if extra_fields:
            log_data["extra"] = _redact_sensitive(extra_fields)

        return json.dumps(log_data, default=str)


def get_request_logger(request=None):
    """
    Get a logger with request context attached.
    Usage:
        logger = get_request_logger(request)
        logger.info("Processing request", extra={"user_id": request.user.id})
    """
    logger = logging.getLogger("builder")
    
    if request:
        # Create a LoggerAdapter with request context
        extra = {
            "request_id": getattr(request, "request_id", None),
            "user_id": request.user.id if hasattr(request, "user") and request.user.is_authenticated else None,
            "path": request.path if hasattr(request, "path") else None,
            "method": request.method if hasattr(request, "method") else None,
        }
        return logging.LoggerAdapter(logger, extra)
    
    return logger
