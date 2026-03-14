import os
import sys
from pathlib import Path
from wsgiref.simple_server import make_server


def main() -> None:
    current_dir = Path(__file__).resolve().parent
    deps_dir = current_dir / ".deps"
    if deps_dir.exists():
        sys.path.insert(0, str(deps_dir))

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    from config.wsgi import application

    host = os.environ.get("RUN_BACKEND_HOST", "127.0.0.1")
    port = int(os.environ.get("RUN_BACKEND_PORT", "8000"))

    server = make_server(host, port, application)
    print(f"Serving backend at http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
