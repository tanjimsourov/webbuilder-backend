from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AppError(Exception):
    code: str
    message: str
    status_code: int = 500
    details: Any | None = None

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.code}: {self.message}"


class ValidationAppError(AppError):
    def __init__(self, message: str = "Validation error.", *, details: Any | None = None):
        super().__init__("validation_error", message, status_code=400, details=details)


class AuthenticationError(AppError):
    def __init__(self, message: str = "Authentication required.", *, details: Any | None = None):
        super().__init__("authentication_error", message, status_code=401, details=details)


class AuthorizationError(AppError):
    def __init__(self, message: str = "Not authorized.", *, details: Any | None = None):
        super().__init__("authorization_error", message, status_code=403, details=details)


class NotFoundError(AppError):
    def __init__(self, message: str = "Not found.", *, details: Any | None = None):
        super().__init__("not_found", message, status_code=404, details=details)


class ConflictError(AppError):
    def __init__(self, message: str = "Conflict.", *, details: Any | None = None):
        super().__init__("conflict", message, status_code=409, details=details)


class RateLimitError(AppError):
    def __init__(self, message: str = "Rate limit exceeded.", *, details: Any | None = None):
        super().__init__("rate_limit", message, status_code=429, details=details)


class InternalServerError(AppError):
    def __init__(self, message: str = "Internal server error.", *, details: Any | None = None):
        super().__init__("internal_server_error", message, status_code=500, details=details)

