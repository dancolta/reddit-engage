#!/usr/bin/env python3
"""Atomic 0o600 writer for dataforseo.yml.

Persists DataForSEO Basic-Auth credentials (login + password) to
`~/.config/subscope/dataforseo.yml`. Used by /subscope-onboard when the
DataForSEO MCP is missing but the user pastes credentials.

Reads YAML-shaped content from stdin (must include `login` and `password`).

Usage:
    cat <<EOF | python3 -m scripts.write_dataforseo_config
    login: user@example.com
    password: hex_token
    EOF
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from subscope.lib import store  # noqa: E402


def _parse_minimal_yaml(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        print("error: empty stdin", file=sys.stderr)
        return 1
    parsed = _parse_minimal_yaml(raw)
    if not parsed.get("login") or not parsed.get("password"):
        print("error: stdin must include 'login' and 'password' lines",
              file=sys.stderr)
        return 1

    out_path = store.xdg_config_dir() / "dataforseo.yml"
    fd = os.open(str(out_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write("# subscope DataForSEO config — chmod 600, never commit to git\n")
            f.write(f"login: {parsed['login']}\n")
            f.write(f"password: {parsed['password']}\n")
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
