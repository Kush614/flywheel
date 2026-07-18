"""Minimal .env loader — no python-dotenv dependency (keeps the core dep-free).

Loads KEY=VALUE lines from a .env file into os.environ without overwriting
anything already set in the real environment. Called at server startup and by
the integration smoke tests so the `aws` / `nexla-cli` calls see credentials.
"""
from __future__ import annotations

import os


def load_dotenv(path: str = ".env") -> bool:
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            # strip an inline comment that isn't inside quotes
            if val and val[0] not in "\"'" and "#" in val:
                val = val.split("#", 1)[0].strip()
            val = val.strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = val
    return True
