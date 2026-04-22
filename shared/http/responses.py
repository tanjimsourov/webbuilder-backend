from __future__ import annotations

from typing import Any

from rest_framework.response import Response


def success(data: Any = None, *, meta: dict[str, Any] | None = None, status: int = 200) -> Response:
    payload: dict[str, Any] = {"ok": True, "data": data}
    if meta is not None:
        payload["meta"] = meta
    return Response(payload, status=status)


def error(
    *,
    code: str,
    message: str,
    status: int,
    details: Any | None = None,
    request_id: str | None = None,
) -> Response:
    payload: dict[str, Any] = {"ok": False, "error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    if request_id:
        payload["request_id"] = request_id
    return Response(payload, status=status)

