#!/usr/bin/env python
import os
import sys
from pathlib import Path


def main() -> None:
    current_dir = Path(__file__).resolve().parent
    deps_dir = current_dir / ".deps"
    if deps_dir.exists():
        sys.path.insert(0, str(deps_dir))

    try:
        from shared.config.dotenv import load_dotenv

        load_dotenv(current_dir / ".env")
    except Exception:
        # Environment loading must never prevent management commands from running.
        pass

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
