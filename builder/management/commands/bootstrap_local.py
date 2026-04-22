from __future__ import annotations

import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.text import slugify

from core.models import Site, SiteMembership, UserAccount, Workspace, WorkspaceMembership


class Command(BaseCommand):
    help = "Create minimal local bootstrap data (user/workspace/site) for development."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="localadmin", help="Bootstrap username.")
        parser.add_argument("--email", default="localadmin@example.test", help="Bootstrap email.")
        parser.add_argument("--password", default="", help="Optional explicit password.")
        parser.add_argument("--workspace", default="Local Workspace", help="Workspace name.")
        parser.add_argument("--site", default="Local Site", help="Site name.")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("bootstrap_local is restricted to DEBUG/local development environments.")

        username = str(options["username"]).strip()
        email = str(options["email"]).strip().lower()
        workspace_name = str(options["workspace"]).strip() or "Local Workspace"
        site_name = str(options["site"]).strip() or "Local Site"

        if not username or not email:
            raise CommandError("Both username and email are required.")

        user_model = get_user_model()
        generated_password = False
        password = str(options["password"]).strip()
        if not password:
            password = secrets.token_urlsafe(18)
            generated_password = True

        user, user_created = user_model.objects.get_or_create(
            username=username,
            defaults={"email": email, "is_staff": True},
        )
        if user_created:
            user.set_password(password)
            user.save(update_fields=["password"])

        account_defaults = {
            "email": email,
            "status": UserAccount.STATUS_ACTIVE,
            "email_verified_at": timezone.now(),
            "terms_accepted_at": timezone.now(),
            "privacy_accepted_at": timezone.now(),
            "data_processing_consent_at": timezone.now(),
        }
        account, _ = UserAccount.objects.get_or_create(user=user, defaults=account_defaults)
        if account.email != email:
            account.email = email
            account.save(update_fields=["email", "updated_at"])

        workspace_slug = slugify(workspace_name) or "local-workspace"
        workspace, workspace_created = Workspace.objects.get_or_create(
            slug=workspace_slug,
            defaults={
                "name": workspace_name,
                "owner": user,
                "status": Workspace.STATUS_ACTIVE,
                "settings": {"seeded_by": "bootstrap_local"},
            },
        )
        if workspace.owner_id != user.id:
            workspace.owner = user
            workspace.save(update_fields=["owner", "updated_at"])

        WorkspaceMembership.objects.get_or_create(
            workspace=workspace,
            user=user,
            defaults={
                "role": WorkspaceMembership.ROLE_OWNER,
                "status": WorkspaceMembership.STATUS_ACTIVE,
                "accepted_at": timezone.now(),
            },
        )

        site_slug = slugify(site_name) or "local-site"
        site, site_created = Site.objects.get_or_create(
            slug=site_slug,
            defaults={
                "name": site_name,
                "workspace": workspace,
                "settings": {"seeded_by": "bootstrap_local"},
            },
        )
        if site.workspace_id != workspace.id:
            site.workspace = workspace
            site.save(update_fields=["workspace", "updated_at"])

        SiteMembership.objects.get_or_create(
            site=site,
            user=user,
            defaults={
                "role": SiteMembership.ROLE_SITE_OWNER,
                "status": SiteMembership.STATUS_ACTIVE,
                "accepted_at": timezone.now(),
            },
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Local bootstrap ready: user={user.username}, workspace={workspace.slug}, site={site.slug}"
            )
        )
        if generated_password and user_created:
            self.stdout.write(self.style.WARNING(f"Generated password: {password}"))
        elif generated_password:
            self.stdout.write("Existing user detected; password unchanged.")
