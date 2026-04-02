"""Notification-domain upload validation helpers.

Use these helpers from notification endpoints that accept uploaded files.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError

from builder.upload_validation import validate_upload as _validate_upload


def validate_upload(file_obj) -> None:
    """Validate an uploaded file and raise ``ValidationError`` on failure."""
    is_valid, error_message, _file_kind = _validate_upload(file_obj)
    if not is_valid:
        raise ValidationError(error_message)
