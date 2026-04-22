"""Forms domain service exports and operational hooks."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.utils import timezone

from notifications.services import queue_email_notification, trigger_webhooks

from forms.models import Form, FormSubmission


@dataclass(frozen=True)
class SpamCheckResult:
    is_spam: bool
    score: float
    provider: str
    reason: str = ""


def evaluate_form_spam(*, form: Form, payload: dict[str, Any], user_agent: str = "", ip_address: str = "") -> SpamCheckResult:
    text_blob = f"{payload} {user_agent} {ip_address}".lower()
    score = 0.0
    markers = ("http://", "https://", "viagra", "casino", "buy now", "crypto giveaway")
    for marker in markers:
        if marker in text_blob:
            score += 0.2
    if form.enable_captcha:
        score = max(0.0, score - 0.1)
    threshold = float(getattr(settings, "FORM_SPAM_THRESHOLD", 0.7))
    is_spam = score >= threshold
    return SpamCheckResult(is_spam=is_spam, score=min(score, 1.0), provider="heuristic", reason="keyword_heuristics")


def queue_form_email_notifications(*, form: Form, submission: FormSubmission) -> int:
    notified = 0
    recipients = [str(value).strip() for value in (form.notify_emails or []) if str(value).strip()]
    for recipient_email in recipients[:20]:
        queue_email_notification(
            recipient=None,
            workspace=form.site.workspace if form.site and form.site.workspace_id else None,
            site=form.site,
            subject=f"New form submission: {form.name}",
            body=f"Submission #{submission.id} received at {timezone.now().isoformat()}",
            payload={
                "form_id": form.id,
                "form_slug": form.slug,
                "submission_id": submission.id,
                "recipient_email": recipient_email,
                "submission_payload": submission.payload,
            },
        )
        notified += 1
    return notified


def export_form_submissions_csv(*, form: Form) -> str:
    queryset = FormSubmission.objects.filter(site=form.site, form_name=form.slug).order_by("-created_at")
    all_keys: list[str] = []
    seen = set()
    for submission in queryset[:5000]:
        payload = submission.payload if isinstance(submission.payload, dict) else {}
        for key in payload.keys():
            key_text = str(key)
            if key_text not in seen:
                seen.add(key_text)
                all_keys.append(key_text)

    rows = io.StringIO()
    writer = csv.DictWriter(rows, fieldnames=["submission_id", "created_at", "status", *all_keys], extrasaction="ignore")
    writer.writeheader()
    for submission in queryset[:5000]:
        payload = submission.payload if isinstance(submission.payload, dict) else {}
        row = {
            "submission_id": submission.id,
            "created_at": submission.created_at.isoformat(),
            "status": submission.status,
        }
        for key in all_keys:
            value = payload.get(key, "")
            row[key] = value if isinstance(value, (str, int, float, bool)) else str(value)
        writer.writerow(row)
    return rows.getvalue()


__all__ = [
    "SpamCheckResult",
    "evaluate_form_spam",
    "export_form_submissions_csv",
    "queue_form_email_notifications",
    "trigger_webhooks",
]
