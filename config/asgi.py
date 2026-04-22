import os
import sys
from pathlib import Path

from django.core.asgi import get_asgi_application


BASE_DIR = Path(__file__).resolve().parent.parent
DEPS_DIR = BASE_DIR / ".deps"
if DEPS_DIR.exists():
    sys.path.insert(0, str(DEPS_DIR))

try:
    from shared.config.dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except Exception:
    pass

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()
