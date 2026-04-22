from __future__ import annotations

from pathlib import Path
from typing import MutableMapping


def load_dotenv(path: str | Path, *, env: MutableMapping[str, str] | None = None, override: bool = False) -> bool:
    """Load a dotenv file into the process environment.

    - Does not require external dependencies.
    - Ignores unknown/invalid lines.
    - By default does not override existing environment variables.
    """

    env = env or __import__("os").environ
    dotenv_path = Path(path)
    if not dotenv_path.exists() or not dotenv_path.is_file():
        return False

    for raw_line in dotenv_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue

        value = value.strip()
        if value and ((value[0] == value[-1]) and value[0] in {"'", '"'}):
            value = value[1:-1]

        if not override and key in env and str(env.get(key) or "").strip():
            continue
        env[key] = value

    return True

