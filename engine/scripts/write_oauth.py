#!/usr/bin/env python3
"""Atomic 0o600 writer for oauth.json. Reads JSON from stdin, writes to XDG config dir.

Why this exists (security F3): shell heredoc + post-hoc chmod has a race window
where the file briefly has default umask perms (commonly 0o644 → world-readable)
before the chmod fires. This script uses os.open(O_CREAT|O_EXCL or O_TRUNC, 0o600)
so the file never exists with permissive bits.

Usage:
    cat oauth.json | python3 -m scripts.write_oauth
or:
    echo '{"client_id":"...","client_secret":"...","username":"...",
           "user_agent":"subscope/0.1 by u/<name>"}' | python3 -m scripts.write_oauth
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Allow running from a checkout: add engine/ to path so we can import the lib.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from subscope.lib import store  # noqa: E402


REQUIRED = ("client_id", "client_secret", "username", "user_agent")


def main() -> int:
    raw = sys.stdin.read().strip()
    if not raw:
        print("error: empty stdin (pipe oauth JSON in)", file=sys.stderr)
        return 1
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"error: stdin is not valid JSON ({e})", file=sys.stderr)
        return 1
    if not isinstance(data, dict):
        print("error: stdin JSON must be an object", file=sys.stderr)
        return 1
    missing = [k for k in REQUIRED if not data.get(k)]
    if missing:
        print(f"error: missing required field(s): {', '.join(missing)}", file=sys.stderr)
        return 1

    out_path = store.xdg_config_dir() / "oauth.json"
    # O_WRONLY|O_CREAT|O_TRUNC with mode 0o600 — file is owner-only from
    # the moment it appears on disk. No umask race.
    fd = os.open(str(out_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
    except Exception:
        # If something went wrong, kill the file rather than leave a half-written one.
        try:
            os.unlink(out_path)
        except OSError:
            pass
        raise
    # Defense in depth: re-chmod in case umask snuck in via fdopen.
    try:
        os.chmod(str(out_path), 0o600)
    except OSError:
        pass
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
