import os
import subprocess

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ...payload_service import (
    payload_dependencies_ready,
    payload_ecommerce_database_configured,
    payload_ecommerce_launch_command,
    payload_ecommerce_secret_configured,
    payload_ecommerce_stripe_configured,
    payload_install_command,
    payload_node_binary,
    payload_root,
    payload_template_exists,
)


class Command(BaseCommand):
    help = "Run the vendored Payload ecommerce template as a commerce companion."

    def add_arguments(self, parser):
        parser.add_argument("--host", default=settings.PAYLOAD_ECOMMERCE_HOST)
        parser.add_argument("--port", type=int, default=settings.PAYLOAD_ECOMMERCE_PORT)

    def handle(self, *args, **options):
        root = payload_root()
        if not payload_template_exists("ecommerce"):
            raise CommandError(f"Payload ecommerce template is missing at {root}")
        if not payload_dependencies_ready():
            raise CommandError(
                "Payload dependencies are not installed. Run "
                f"`{payload_install_command()}` from {root} first."
            )
        if not payload_ecommerce_database_configured():
            raise CommandError("Payload ecommerce requires PAYLOAD_ECOMMERCE_DATABASE_URL before launching.")
        if not payload_ecommerce_secret_configured():
            raise CommandError("Payload ecommerce requires PAYLOAD_ECOMMERCE_SECRET before launching.")
        if not payload_ecommerce_stripe_configured():
            raise CommandError(
                "Payload ecommerce requires PAYLOAD_ECOMMERCE_STRIPE_SECRET_KEY, "
                "PAYLOAD_ECOMMERCE_STRIPE_PUBLISHABLE_KEY, and "
                "PAYLOAD_ECOMMERCE_STRIPE_WEBHOOK_SECRET before launching."
            )

        pnpm_binary = payload_node_binary()
        configured_public_url = (settings.PAYLOAD_ECOMMERCE_PUBLIC_URL or "").strip()
        public_url = configured_public_url.rstrip("/") if configured_public_url else f"http://{options['host']}:{options['port']}"
        env = os.environ.copy()
        env["HOSTNAME"] = str(options["host"])
        env["PORT"] = str(options["port"])
        env["NEXT_TELEMETRY_DISABLED"] = "1"
        env["DATABASE_URL"] = settings.PAYLOAD_ECOMMERCE_DATABASE_URL
        env["PAYLOAD_SECRET"] = settings.PAYLOAD_ECOMMERCE_SECRET
        env["PREVIEW_SECRET"] = settings.PAYLOAD_ECOMMERCE_PREVIEW_SECRET or settings.PAYLOAD_ECOMMERCE_SECRET
        env["NEXT_PUBLIC_SERVER_URL"] = public_url
        env["PAYLOAD_PUBLIC_SERVER_URL"] = public_url
        env["STRIPE_SECRET_KEY"] = settings.PAYLOAD_ECOMMERCE_STRIPE_SECRET_KEY
        env["NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY"] = settings.PAYLOAD_ECOMMERCE_STRIPE_PUBLISHABLE_KEY
        env["STRIPE_WEBHOOKS_SIGNING_SECRET"] = settings.PAYLOAD_ECOMMERCE_STRIPE_WEBHOOK_SECRET

        command = [pnpm_binary, "--filter", "ecommerce", "dev"]

        self.stdout.write(
            self.style.SUCCESS(
                f"Starting Payload ecommerce from {root} on {options['host']}:{options['port']} via {payload_ecommerce_launch_command()}"
            )
        )
        try:
            subprocess.run(command, cwd=root, env=env, check=True)
        except FileNotFoundError as exc:
            raise CommandError("pnpm was not found on PATH. Install pnpm first.") from exc
        except subprocess.CalledProcessError as exc:
            raise CommandError(f"Payload ecommerce exited with status {exc.returncode}") from exc
