#!/usr/bin/env python3
"""Atomic 0o600 writer for slack.json (subscope's optional Slack webhook).

Reads JSON from stdin like:
    {"webhook_url": "https://hooks.slack.com/services/T.../B.../..."}

Writes to ~/.config/subscope/slack.json with owner-only perms applied
atomically (no umask race). Validates the URL host before writing.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from subscope.lib import store  # noqa: E402


def main() -> int:
    raw = sys.stdin.read().strip()
    if not raw:
        print("error: empty stdin", file=sys.stderr)
        return 1
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"error: stdin is not valid JSON ({e})", file=sys.stderr)
        return 1
    url = (data or {}).get("webhook_url") if isinstance(data, dict) else None
    if not url:
        print("error: stdin JSON must include 'webhook_url'", file=sys.stderr)
        return 1
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "hooks.slack.com":
        print(f"error: webhook_url must be https://hooks.slack.com/... (got {url!r})",
              file=sys.stderr)
        return 1

    out_path = store.xdg_config_dir() / "slack.json"
    fd = os.open(str(out_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump({"webhook_url": url}, f, indent=2)
    except Exception:
        try:
            os.unlink(out_path)
        except OSError:
            pass
        raise
    try:
        os.chmod(str(out_path), 0o600)
    except OSError:
        pass
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
