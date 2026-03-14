import os
import subprocess

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ...serpbear_service import (
    serpbear_dependencies_ready,
    serpbear_install_command,
    serpbear_node_binary,
    serpbear_root,
    serpbear_source_exists,
)


class Command(BaseCommand):
    help = "Run the vendored SerpBear companion service."

    def add_arguments(self, parser):
        parser.add_argument("--host", default=settings.SERPBEAR_HOST)
        parser.add_argument("--port", type=int, default=settings.SERPBEAR_PORT)
        parser.add_argument(
            "--production",
            action="store_true",
            default=False,
            help="Run SerpBear with `npm run start` instead of dev mode.",
        )

    def handle(self, *args, **options):
        root = serpbear_root()
        if not serpbear_source_exists():
            raise CommandError(f"SerpBear vendor source is missing at {root}")
        if not serpbear_dependencies_ready():
            raise CommandError(
                "SerpBear dependencies are not installed. Run "
                f"`{serpbear_install_command()}` from {root} first."
            )

        npm_binary = serpbear_node_binary()
        env = os.environ.copy()
        env["HOST"] = str(options["host"])
        env["PORT"] = str(options["port"])
        env["NEXT_TELEMETRY_DISABLED"] = "1"

        command = [npm_binary, "run", "start" if options["production"] else "dev", "--"]
        command.extend(["-H", str(options["host"]), "-p", str(options["port"])])

        self.stdout.write(
            self.style.SUCCESS(
                f"Starting SerpBear from {root} on {options['host']}:{options['port']}"
            )
        )
        try:
            subprocess.run(command, cwd=root, env=env, check=True)
        except FileNotFoundError as exc:
            raise CommandError("npm was not found on PATH. Install Node.js first.") from exc
        except subprocess.CalledProcessError as exc:
            raise CommandError(f"SerpBear exited with status {exc.returncode}") from exc
