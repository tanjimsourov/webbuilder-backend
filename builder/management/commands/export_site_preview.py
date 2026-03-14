from __future__ import annotations

import sys
from pathlib import Path
from importlib.util import spec_from_file_location, module_from_spec

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Export a site's pages as a static preview mirror for the Next.js /preview route."

    def add_arguments(self, parser):
        parser.add_argument("site_slug", type=str, help="Slug of the site to export")

    def handle(self, *args, **options):
        site_slug: str = options["site_slug"]

        backend_dir = Path(__file__).resolve().parents[3]  # .../backend
        script_path = backend_dir / "scripts" / "export_site_preview.py"
        if not script_path.exists():
            raise CommandError(f"Exporter script not found at {script_path}")

        # Dynamically import the exporter script and run main(site_slug)
        spec = spec_from_file_location("_export_site_preview", script_path)
        if spec is None or spec.loader is None:
            raise CommandError("Unable to load exporter module")
        mod = module_from_spec(spec)
        sys.modules["_export_site_preview"] = mod
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]

        exit_code = mod.main(site_slug)
        if exit_code != 0:
            raise CommandError(f"Export failed with code {exit_code}")
        self.stdout.write(self.style.SUCCESS(f"Exported site '{site_slug}' for preview"))
