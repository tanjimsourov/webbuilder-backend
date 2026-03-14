from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives, get_connection
from django.utils import timezone

from .models import PlatformEmailCampaign, PlatformSubscription, Workspace


User = get_user_model()


@dataclass
class CampaignRecipient:
    email: str
    username: str


def _dedupe_recipients(pairs: list[tuple[str, str]]) -> list[CampaignRecipient]:
    unique: dict[str, CampaignRecipient] = {}
    for email, username in pairs:
        normalized = (email or "").strip().lower()
        if not normalized:
            continue
        if normalized not in unique:
            unique[normalized] = CampaignRecipient(email=email.strip(), username=username.strip())
    return list(unique.values())


def platform_campaign_recipients(campaign: PlatformEmailCampaign) -> list[CampaignRecipient]:
    audience = campaign.audience_type

    if audience == PlatformEmailCampaign.AUDIENCE_ALL_USERS:
        raw = list(
            User.objects.filter(is_active=True)
            .exclude(email="")
            .values_list("email", "username")
        )
        return _dedupe_recipients(raw)

    if audience == PlatformEmailCampaign.AUDIENCE_WORKSPACE_OWNERS:
        raw = list(
            Workspace.objects.select_related("owner")
            .exclude(owner__email="")
            .values_list("owner__email", "owner__username")
        )
        return _dedupe_recipients(raw)

    subscription_statuses = {
        PlatformEmailCampaign.AUDIENCE_ACTIVE_SUBSCRIBERS: [PlatformSubscription.STATUS_ACTIVE],
        PlatformEmailCampaign.AUDIENCE_TRIALING: [PlatformSubscription.STATUS_TRIALING],
        PlatformEmailCampaign.AUDIENCE_INACTIVE: [
            PlatformSubscription.STATUS_PAST_DUE,
            PlatformSubscription.STATUS_PAUSED,
            PlatformSubscription.STATUS_CANCELLED,
            PlatformSubscription.STATUS_EXPIRED,
        ],
    }.get(audience, [])

    raw = list(
        Workspace.objects.select_related("owner", "platform_subscription")
        .filter(platform_subscription__status__in=subscription_statuses)
        .exclude(owner__email="")
        .values_list("owner__email", "owner__username")
    )
    return _dedupe_recipients(raw)


def send_platform_campaign(campaign: PlatformEmailCampaign) -> PlatformEmailCampaign:
    recipients = platform_campaign_recipients(campaign)
    campaign.status = PlatformEmailCampaign.STATUS_SENDING
    campaign.recipient_count = len(recipients)
    campaign.sent_count = 0
    campaign.last_error = ""
    campaign.save(update_fields=["status", "recipient_count", "sent_count", "last_error", "updated_at"])

    if not recipients:
        campaign.status = PlatformEmailCampaign.STATUS_FAILED
        campaign.last_error = "No recipients matched this audience."
        campaign.save(update_fields=["status", "last_error", "updated_at"])
        return campaign

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "webmaster@localhost")
    connection = get_connection()
    sent_count = 0

    try:
        for recipient in recipients:
            message = EmailMultiAlternatives(
                subject=campaign.subject,
                body=campaign.body_text,
                from_email=from_email,
                to=[recipient.email],
                connection=connection,
                headers={"X-Platform-Campaign": str(campaign.pk)},
            )
            if campaign.body_html.strip():
                message.attach_alternative(campaign.body_html, "text/html")
            message.send()
            sent_count += 1
    except Exception as exc:
        campaign.status = PlatformEmailCampaign.STATUS_FAILED
        campaign.sent_count = sent_count
        campaign.last_error = str(exc)
        campaign.save(update_fields=["status", "sent_count", "last_error", "updated_at"])
        return campaign

    campaign.status = PlatformEmailCampaign.STATUS_SENT
    campaign.sent_count = sent_count
    campaign.sent_at = timezone.now()
    campaign.last_error = ""
    campaign.save(update_fields=["status", "sent_count", "sent_at", "last_error", "updated_at"])
    return campaign
