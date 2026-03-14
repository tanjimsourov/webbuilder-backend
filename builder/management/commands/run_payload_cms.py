import os
import subprocess

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ...payload_service import (
    payload_cms_database_configured,
    payload_cms_launch_command,
    payload_cms_secret_configured,
    payload_dependencies_ready,
    payload_install_command,
    payload_node_binary,
    payload_root,
    payload_template_exists,
)


class Command(BaseCommand):
    help = "Run the vendored Payload website template as a CMS companion."

    def add_arguments(self, parser):
        parser.add_argument("--host", default=settings.PAYLOAD_CMS_HOST)
        parser.add_argument("--port", type=int, default=settings.PAYLOAD_CMS_PORT)

    def handle(self, *args, **options):
        root = payload_root()
        if not payload_template_exists("website"):
            raise CommandError(f"Payload website template is missing at {root}")
        if not payload_dependencies_ready():
            raise CommandError(
                "Payload dependencies are not installed. Run "
                f"`{payload_install_command()}` from {root} first."
            )
        if not payload_cms_database_configured():
            raise CommandError("Payload CMS requires PAYLOAD_CMS_DATABASE_URL before launching.")
        if not payload_cms_secret_configured():
            raise CommandError("Payload CMS requires PAYLOAD_CMS_SECRET before launching.")

        pnpm_binary = payload_node_binary()
        configured_public_url = (settings.PAYLOAD_CMS_PUBLIC_URL or "").strip()
        public_url = configured_public_url.rstrip("/") if configured_public_url else f"http://{options['host']}:{options['port']}"
        env = os.environ.copy()
        env["HOSTNAME"] = str(options["host"])
        env["PORT"] = str(options["port"])
        env["NEXT_TELEMETRY_DISABLED"] = "1"
        env["DATABASE_URL"] = settings.PAYLOAD_CMS_DATABASE_URL
        env["PAYLOAD_SECRET"] = settings.PAYLOAD_CMS_SECRET
        env["PREVIEW_SECRET"] = settings.PAYLOAD_CMS_PREVIEW_SECRET or settings.PAYLOAD_CMS_SECRET
        env["CRON_SECRET"] = settings.PAYLOAD_CMS_CRON_SECRET or settings.PAYLOAD_CMS_SECRET
        env["NEXT_PUBLIC_SERVER_URL"] = public_url
        env["PAYLOAD_PUBLIC_SERVER_URL"] = public_url

        command = [pnpm_binary, "--filter", "website", "dev"]

        self.stdout.write(
            self.style.SUCCESS(
                f"Starting Payload CMS from {root} on {options['host']}:{options['port']} via {payload_cms_launch_command()}"
            )
        )
        try:
            subprocess.run(command, cwd=root, env=env, check=True)
        except FileNotFoundError as exc:
            raise CommandError("pnpm was not found on PATH. Install pnpm first.") from exc
        except subprocess.CalledProcessError as exc:
            raise CommandError(f"Payload CMS exited with status {exc.returncode}") from exc
