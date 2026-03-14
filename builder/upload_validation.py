"""
File Upload Validation

Provides validation for file uploads including:
- File extension checking
- File size limits
- MIME type validation
- Security checks
- SVG security validation (rejects files containing dangerous elements)

Note on SVG handling:
    This module REJECTS unsafe SVGs rather than sanitizing them. This is the
    safer approach for a CMS - we do not attempt to clean malicious content,
    we simply refuse to accept it. Users must upload clean SVG files.
    
    The `sanitize_svg()` function exists for potential future use cases where
    sanitization is preferred over rejection, but it is not used in the
    default upload flow.
"""

import os
import re
import mimetypes
from typing import Tuple

from django.conf import settings
from django.core.exceptions import ValidationError


# Dangerous SVG elements and attributes that can execute JavaScript
SVG_DANGEROUS_TAGS = {
    'script', 'handler', 'foreignobject', 'set', 'animate', 'animatemotion',
    'animatetransform', 'discard', 'use', 'iframe', 'embed', 'object',
}
SVG_DANGEROUS_ATTRS = {
    'onload', 'onclick', 'onerror', 'onmouseover', 'onmouseout', 'onmousemove',
    'onfocus', 'onblur', 'onchange', 'onsubmit', 'onreset', 'onselect',
    'onkeydown', 'onkeypress', 'onkeyup', 'onabort', 'ondblclick',
    'onmousedown', 'onmouseup', 'onscroll', 'onwheel', 'oncontextmenu',
    'href',  # Can contain javascript: URLs
}


def sanitize_svg(content: bytes) -> bytes:
    """
    Sanitize SVG content by removing dangerous elements and attributes.
    Returns sanitized SVG bytes.
    
    NOTE: This function is NOT used in the default upload flow. The default
    behavior is to REJECT unsafe SVGs via `is_svg_safe()` and `validate_svg_content()`.
    This function is provided for use cases where sanitization is preferred.
    """
    try:
        text = content.decode('utf-8', errors='replace')
    except Exception:
        return content

    # Remove script tags and their content
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.IGNORECASE | re.DOTALL)
    
    # Remove dangerous tags (self-closing and paired)
    for tag in SVG_DANGEROUS_TAGS:
        text = re.sub(rf'<{tag}[^>]*>.*?</{tag}>', '', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(rf'<{tag}[^>]*/>', '', text, flags=re.IGNORECASE)
        text = re.sub(rf'<{tag}[^>]*>', '', text, flags=re.IGNORECASE)
    
    # Remove dangerous attributes (on* event handlers)
    for attr in SVG_DANGEROUS_ATTRS:
        text = re.sub(rf'\s{attr}\s*=\s*["\'][^"\']*["\']', '', text, flags=re.IGNORECASE)
        text = re.sub(rf'\s{attr}\s*=\s*[^\s>]+', '', text, flags=re.IGNORECASE)
    
    # Remove javascript: URLs in any attribute
    text = re.sub(r'javascript\s*:', '', text, flags=re.IGNORECASE)
    
    # Remove data: URLs that could contain scripts
    text = re.sub(r'data\s*:\s*text/html', 'data:text/plain', text, flags=re.IGNORECASE)
    
    return text.encode('utf-8')


def is_svg_safe(content: bytes) -> Tuple[bool, str]:
    """
    Check if SVG content is safe (no scripts or dangerous elements).
    Returns (is_safe, error_message).
    """
    try:
        text = content.decode('utf-8', errors='replace').lower()
    except Exception:
        return False, "Unable to decode SVG content."
    
    # Check for script tags
    if '<script' in text:
        return False, "SVG contains script elements which are not allowed."
    
    # Check for dangerous tags
    for tag in SVG_DANGEROUS_TAGS:
        if f'<{tag}' in text:
            return False, f"SVG contains dangerous element '{tag}' which is not allowed."
    
    # Check for event handlers
    for attr in SVG_DANGEROUS_ATTRS:
        if re.search(rf'\s{attr}\s*=', text):
            return False, f"SVG contains dangerous attribute '{attr}' which is not allowed."
    
    # Check for javascript: URLs
    if 'javascript:' in text:
        return False, "SVG contains javascript: URLs which are not allowed."
    
    return True, ""


# MIME type to extension mapping for validation
MIME_TYPE_EXTENSIONS = {
    "image/jpeg": ["jpg", "jpeg"],
    "image/png": ["png"],
    "image/gif": ["gif"],
    "image/webp": ["webp"],
    "image/svg+xml": ["svg"],
    "image/x-icon": ["ico"],
    "image/bmp": ["bmp"],
    "image/tiff": ["tiff", "tif"],
    "application/pdf": ["pdf"],
    "application/msword": ["doc"],
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ["docx"],
    "application/vnd.ms-excel": ["xls"],
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ["xlsx"],
    "application/vnd.ms-powerpoint": ["ppt"],
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ["pptx"],
    "text/plain": ["txt"],
    "text/csv": ["csv"],
    "video/mp4": ["mp4"],
    "video/webm": ["webm"],
    "video/quicktime": ["mov"],
    "video/x-msvideo": ["avi"],
    "audio/mpeg": ["mp3"],
    "audio/wav": ["wav"],
    "audio/ogg": ["ogg"],
    "application/zip": ["zip"],
}


def get_file_extension(filename: str) -> str:
    """Get lowercase file extension without the dot."""
    if not filename:
        return ""
    ext = os.path.splitext(filename)[1].lower()
    return ext[1:] if ext.startswith(".") else ext


def get_file_kind(extension: str) -> str:
    """Determine file kind from extension."""
    image_exts = {"jpg", "jpeg", "png", "gif", "webp", "svg", "ico", "bmp", "tiff", "tif"}
    video_exts = {"mp4", "webm", "mov", "avi", "mkv"}
    audio_exts = {"mp3", "wav", "ogg", "flac", "aac"}
    document_exts = {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "csv"}

    ext = extension.lower()
    if ext in image_exts:
        return "image"
    elif ext in video_exts:
        return "video"
    elif ext in audio_exts:
        return "audio"
    elif ext in document_exts:
        return "document"
    return "other"


def get_max_size_for_kind(kind: str) -> int:
    """Get maximum file size for a file kind."""
    if kind == "image":
        return getattr(settings, "MAX_IMAGE_SIZE", 5 * 1024 * 1024)
    elif kind == "video":
        return getattr(settings, "MAX_VIDEO_SIZE", 100 * 1024 * 1024)
    elif kind in ("document", "audio"):
        return getattr(settings, "MAX_DOCUMENT_SIZE", 20 * 1024 * 1024)
    return getattr(settings, "DATA_UPLOAD_MAX_MEMORY_SIZE", 10 * 1024 * 1024)


def validate_file_extension(filename: str) -> Tuple[bool, str]:
    """
    Validate file extension against allowed/blocked lists.
    Returns (is_valid, error_message).
    """
    ext = get_file_extension(filename)
    
    if not ext:
        return False, "File must have an extension."
    
    # Check blocked extensions
    blocked = getattr(settings, "BLOCKED_UPLOAD_EXTENSIONS", [])
    if ext in [b.lower() for b in blocked]:
        return False, f"File type '.{ext}' is not allowed for security reasons."
    
    # Check allowed extensions
    allowed = getattr(settings, "ALLOWED_UPLOAD_EXTENSIONS", [])
    if allowed and ext not in [a.lower() for a in allowed]:
        return False, f"File type '.{ext}' is not supported. Allowed types: {', '.join(allowed[:10])}..."
    
    return True, ""


def validate_file_size(file, filename: str = None) -> Tuple[bool, str]:
    """
    Validate file size against limits.
    Returns (is_valid, error_message).
    """
    # Get file size
    if hasattr(file, "size"):
        size = file.size
    elif hasattr(file, "seek") and hasattr(file, "tell"):
        file.seek(0, 2)  # Seek to end
        size = file.tell()
        file.seek(0)  # Reset to beginning
    else:
        return True, ""  # Can't determine size, allow
    
    # Get extension and kind
    ext = get_file_extension(filename or getattr(file, "name", ""))
    kind = get_file_kind(ext)
    max_size = get_max_size_for_kind(kind)
    
    if size > max_size:
        max_mb = max_size / (1024 * 1024)
        size_mb = size / (1024 * 1024)
        return False, f"File size ({size_mb:.1f}MB) exceeds maximum allowed ({max_mb:.1f}MB) for {kind} files."
    
    return True, ""


def validate_mime_type(file, filename: str = None) -> Tuple[bool, str]:
    """
    Validate MIME type matches extension.
    Returns (is_valid, error_message).
    """
    ext = get_file_extension(filename or getattr(file, "name", ""))
    
    # Try to detect MIME type
    if hasattr(file, "content_type"):
        mime_type = file.content_type
    else:
        mime_type, _ = mimetypes.guess_type(filename or getattr(file, "name", ""))
    
    if not mime_type:
        return True, ""  # Can't determine, allow
    
    # Check if extension matches expected MIME type
    expected_exts = MIME_TYPE_EXTENSIONS.get(mime_type, [])
    if expected_exts and ext not in expected_exts:
        # This could indicate a disguised file
        return False, f"File content type ({mime_type}) doesn't match extension (.{ext})."
    
    return True, ""


def validate_svg_content(file) -> Tuple[bool, str]:
    """
    Validate SVG file content for security.
    Returns (is_valid, error_message).
    """
    try:
        # Read file content
        if hasattr(file, 'read'):
            pos = file.tell() if hasattr(file, 'tell') else 0
            content = file.read()
            if hasattr(file, 'seek'):
                file.seek(pos)
        else:
            return True, ""  # Can't read content, skip check
        
        if isinstance(content, str):
            content = content.encode('utf-8')
        
        # Check if SVG is safe
        is_safe, error = is_svg_safe(content)
        if not is_safe:
            return False, error
        
        return True, ""
    except Exception as e:
        return False, f"Error validating SVG: {str(e)}"


def validate_upload(file, filename: str = None, sanitize_svg_content: bool = True) -> Tuple[bool, str, str]:
    """
    Full validation of an uploaded file.
    Returns (is_valid, error_message, file_kind).
    
    If sanitize_svg_content is True and file is SVG, the file content will be
    validated for dangerous elements. Set to False to skip SVG content validation.
    """
    fname = filename or getattr(file, "name", "")
    
    # Extension check
    valid, error = validate_file_extension(fname)
    if not valid:
        return False, error, ""
    
    # Size check
    valid, error = validate_file_size(file, fname)
    if not valid:
        return False, error, ""
    
    # MIME type check
    valid, error = validate_mime_type(file, fname)
    if not valid:
        return False, error, ""
    
    ext = get_file_extension(fname)
    kind = get_file_kind(ext)
    
    # SVG security check
    if sanitize_svg_content and ext == 'svg':
        valid, error = validate_svg_content(file)
        if not valid:
            return False, error, ""
    
    return True, "", kind


class FileUploadValidator:
    """Django validator for file uploads."""
    
    def __init__(self, allowed_kinds: list = None, max_size: int = None):
        self.allowed_kinds = allowed_kinds
        self.max_size = max_size
    
    def __call__(self, file):
        valid, error, kind = validate_upload(file)
        
        if not valid:
            raise ValidationError(error)
        
        if self.allowed_kinds and kind not in self.allowed_kinds:
            raise ValidationError(f"Only {', '.join(self.allowed_kinds)} files are allowed.")
        
        if self.max_size and hasattr(file, "size") and file.size > self.max_size:
            max_mb = self.max_size / (1024 * 1024)
            raise ValidationError(f"File size exceeds maximum allowed ({max_mb:.1f}MB).")
