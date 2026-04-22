from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from core.models import UserAccount, UserSecurityState


def _normalized_email(user) -> str:
    raw = (getattr(user, "email", "") or "").strip().lower()
    if raw:
        return raw
    return f"user-{user.pk}@local.invalid"


def _unique_email_for(user) -> str:
    base = _normalized_email(user)
    candidate = base
    suffix = 2
    while UserAccount.objects.exclude(user=user).filter(email=candidate).exists():
        local, _, domain = base.partition("@")
        candidate = f"{local}+{suffix}@{domain}" if domain else f"{local}+{suffix}"
        suffix += 1
    return candidate


@receiver(post_save, sender=get_user_model())
def ensure_user_account_and_security(sender, instance, created, **kwargs):
    email = _unique_email_for(instance)
    defaults = {
        "email": email,
        "display_name": (instance.get_full_name() or instance.username).strip()[:160],
    }
    account, account_created = UserAccount.objects.get_or_create(user=instance, defaults=defaults)
    if not account_created:
        updates: list[str] = []
        if account.email != email:
            account.email = email
            updates.append("email")
        desired_name = (instance.get_full_name() or instance.username).strip()[:160]
        if desired_name and account.display_name != desired_name and not account.display_name:
            account.display_name = desired_name
            updates.append("display_name")
        if updates:
            account.save(update_fields=[*updates, "updated_at"])

    UserSecurityState.objects.get_or_create(user=instance)
