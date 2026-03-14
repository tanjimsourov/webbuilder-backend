import importlib.util
import os
import subprocess
import sys

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ...librecrawl_service import librecrawl_install_command, librecrawl_main_path, librecrawl_root


def _missing_dependencies() -> list[str]:
    required_modules = [
        "flask",
        "flask_compress",
        "waitress",
        "bcrypt",
        "markdown",
        "dotenv",
    ]
    return [name for name in required_modules if importlib.util.find_spec(name) is None]


class Command(BaseCommand):
    help = "Run the vendored LibreCrawl companion service."

    def add_arguments(self, parser):
        parser.add_argument("--host", default=settings.LIBRECRAWL_HOST)
        parser.add_argument("--port", type=int, default=settings.LIBRECRAWL_PORT)
        parser.add_argument(
            "--public-url",
            default=settings.LIBRECRAWL_PUBLIC_URL or "",
            help="Optional externally reachable URL shown in the UI.",
        )
        parser.add_argument(
            "--local",
            action="store_true",
            default=settings.LIBRECRAWL_LOCAL_MODE,
            help="Run LibreCrawl in local mode.",
        )
        parser.add_argument(
            "--no-local",
            action="store_false",
            dest="local",
            help="Force LibreCrawl out of local mode.",
        )
        parser.add_argument(
            "--disable-register",
            action="store_true",
            default=False,
            help="Disable registration in the vendored LibreCrawl service.",
        )
        parser.add_argument(
            "--disable-guest",
            action="store_true",
            default=False,
            help="Disable guest logins in the vendored LibreCrawl service.",
        )

    def handle(self, *args, **options):
        root = librecrawl_root()
        main_path = librecrawl_main_path()
        if not main_path.exists():
            raise CommandError(f"LibreCrawl vendor source is missing at {main_path}")

        missing = _missing_dependencies()
        if missing:
            missing_list = ", ".join(sorted(missing))
            raise CommandError(
                "LibreCrawl dependencies are not installed "
                f"({missing_list}). Run `{librecrawl_install_command()}` from the backend directory."
            )

        env = os.environ.copy()
        env["LIBRECRAWL_HOST"] = str(options["host"])
        env["LIBRECRAWL_PORT"] = str(options["port"])
        env["LIBRECRAWL_OPEN_BROWSER"] = "0"
        env["LIBRECRAWL_LOCAL_MODE"] = "1" if options["local"] else "0"
        env["LIBRECRAWL_SECRET_KEY"] = settings.LIBRECRAWL_SECRET_KEY
        if options["public_url"]:
            env["LIBRECRAWL_PUBLIC_URL"] = options["public_url"]

        command = [sys.executable, str(main_path)]
        if options["local"]:
            command.append("--local")
        if options["disable_register"]:
            command.append("--disable-register")
        if options["disable_guest"]:
            command.append("--disable-guest")

        self.stdout.write(
            self.style.SUCCESS(
                f"Starting LibreCrawl from {root} on {options['host']}:{options['port']}"
            )
        )
        try:
            subprocess.run(command, cwd=root, env=env, check=True)
        except subprocess.CalledProcessError as exc:
            raise CommandError(f"LibreCrawl exited with status {exc.returncode}") from exc
