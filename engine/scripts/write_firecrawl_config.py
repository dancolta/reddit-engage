#!/usr/bin/env python3
"""Atomic 0o600 writer for firecrawl.yml.

Persists a Firecrawl API key to `~/.config/subscope/firecrawl.yml`. Used by
/subscope:onboard when Firecrawl is opted in but neither the seo-firecrawl
skill nor a FIRECRAWL_API_KEY env var is detected.

Reads YAML-shaped content from stdin (must include `api_key`).

Usage:
    cat <<EOF | python3 -m scripts.write_firecrawl_config
    api_key: fc-xxxxxxxxxxxx
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
    if not parsed.get("api_key"):
        print("error: stdin must include 'api_key' line", file=sys.stderr)
        return 1

    out_path = store.xdg_config_dir() / "firecrawl.yml"
    fd = os.open(str(out_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write("# subscope Firecrawl config — chmod 600, never commit to git\n")
            f.write(f"api_key: {parsed['api_key']}\n")
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
