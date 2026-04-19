"""
Send a Telegram message via Bot API.
Credentials are loaded from ~/.env — never hardcoded.

Usage:
    python send_telegram.py "your message here"

Required ~/.env entries:
    TELEGRAM_BOT_TOKEN=your_bot_token
    TELEGRAM_CHAT_ID=your_chat_id

Supports Telegram HTML parse mode:
    <b>bold</b>, <i>italic</i>, <code>inline code</code>,
    <pre>code block</pre>, <u>underline</u>, <s>strikethrough</s>,
    <a href="url">link text</a>
"""

import sys
import os
import requests
from pathlib import Path

# Load from ~/.env before accessing environment
_here = Path(__file__).parent
_loader = _here / "env_loader.py"
if _loader.exists():
    import importlib.util
    spec = importlib.util.spec_from_file_location("env_loader", _loader)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.load_env()
else:
    # Fallback: inline loader if env_loader.py is missing
    _env_file = Path.home() / ".env"
    if _env_file.exists():
        with open(_env_file, encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _, _v = _line.partition("=")
                    os.environ.setdefault(_k.strip(), _v.strip())

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def send_message(text: str) -> None:
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("Error: TELEGRAM_BOT_TOKEN not set. Add it to ~/.env")
        sys.exit(1)
    if not CHAT_ID or CHAT_ID == "YOUR_CHAT_ID_HERE":
        print("Error: TELEGRAM_CHAT_ID not set. Add it to ~/.env")
        sys.exit(1)

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    response = requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    })
    response.raise_for_status()
    print("Message sent.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python send_telegram.py "your message here"')
        sys.exit(1)
    send_message(" ".join(sys.argv[1:]))
