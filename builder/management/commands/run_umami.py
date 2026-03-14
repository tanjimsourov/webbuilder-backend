import os
import subprocess

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ...umami_service import (
    umami_database_configured,
    umami_dependencies_ready,
    umami_install_command,
    umami_node_binary,
    umami_root,
    umami_source_exists,
)


class Command(BaseCommand):
    help = "Run the vendored Umami analytics companion service."

    def add_arguments(self, parser):
        parser.add_argument("--host", default=settings.UMAMI_HOST)
        parser.add_argument("--port", type=int, default=settings.UMAMI_PORT)

    def handle(self, *args, **options):
        root = umami_root()
        if not umami_source_exists():
            raise CommandError(f"Umami vendor source is missing at {root}")
        if not umami_dependencies_ready():
            raise CommandError(
                "Umami dependencies are not installed. Run "
                f"`{umami_install_command()}` from {root} first."
            )
        if not umami_database_configured():
            raise CommandError(
                "Umami requires a PostgreSQL DATABASE_URL. Set UMAMI_DATABASE_URL or DATABASE_URL before launching."
            )

        pnpm_binary = umami_node_binary()
        env = os.environ.copy()
        env["HOSTNAME"] = str(options["host"])
        env["PORT"] = str(options["port"])
        env["NEXT_TELEMETRY_DISABLED"] = "1"
        if os.environ.get("UMAMI_DATABASE_URL"):
            env["DATABASE_URL"] = os.environ["UMAMI_DATABASE_URL"]

        command = [pnpm_binary, "exec", "next", "dev", "-H", str(options["host"]), "-p", str(options["port"])]

        self.stdout.write(
            self.style.SUCCESS(
                f"Starting Umami from {root} on {options['host']}:{options['port']}"
            )
        )
        try:
            subprocess.run(command, cwd=root, env=env, check=True)
        except FileNotFoundError as exc:
            raise CommandError("pnpm was not found on PATH. Install pnpm first.") from exc
        except subprocess.CalledProcessError as exc:
            raise CommandError(f"Umami exited with status {exc.returncode}") from exc
