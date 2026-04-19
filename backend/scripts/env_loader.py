"""
Shared helper for loading credentials from ~/.env

Place this file in your scripts directory alongside other scripts.
Any script can import and call load_env() before accessing os.environ.

~/.env format:
    TELEGRAM_BOT_TOKEN=your_token_here
    TELEGRAM_CHAT_ID=your_chat_id_here
    SOME_API_KEY=another_key_here
    # Lines starting with # are ignored
"""

import os
from pathlib import Path


def load_env(env_path: str = None) -> None:
    """
    Load key=value pairs from ~/.env into os.environ.
    Skips keys that are already set (env vars take precedence).
    """
    path = Path(env_path) if env_path else Path.home() / ".env"

    if not path.exists():
        return

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Strip surrounding quotes if present
            if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
                value = value[1:-1]
            os.environ.setdefault(key, value)
