#!/usr/bin/env python3
"""Atomic 0o600 writer for notion.yml (subscope's daily-triage DB config).

Why this exists (security F1): the previous flow passed `NOTION_API_KEY=$KEY`
as an inline env var on the command line. That landed the secret in
/proc/<pid>/environ AND in `ps eww` output AND in the shell's command history.
This helper writes a `~/.config/subscope/notion.yml` file with `chmod 600`
applied atomically, so secrets stay on disk, never on the command line.

Accepts either shape:
  Legacy (SDK + manual DB ID):   `api_key` + `database_id`
  MCP-first (OAuth via MCP):     `mode: mcp` + `database_name`

The skill layer is responsible for resolving database_name → ID at write time
via the Notion MCP `search` tool when `mode: mcp`. The engine never reads
the api_key when `mode: mcp`.

Usage:
    cat <<EOF | python3 -m scripts.write_notion_config
    mode: mcp
    database_name: Subscope Daily
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
    """Tiny key:value YAML parser (avoids requiring pyyaml just for two fields).

    Only supports flat `key: value` lines. Ignores blanks and `#` comments.
    """
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

    mode = parsed.get("mode", "").lower()
    is_mcp = mode == "mcp"
    is_legacy = bool(parsed.get("api_key") and parsed.get("database_id"))

    if is_mcp and not parsed.get("database_name"):
        print("error: mode=mcp requires 'database_name' line", file=sys.stderr)
        return 1
    if not is_mcp and not is_legacy:
        print("error: stdin must include either 'mode: mcp' + 'database_name', "
              "or 'api_key' + 'database_id'", file=sys.stderr)
        return 1

    out_path = store.xdg_config_dir() / "notion.yml"
    fd = os.open(str(out_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write("# subscope Notion config, chmod 600, never commit to git\n")
            if is_mcp:
                f.write("mode: mcp\n")
                f.write(f"database_name: {parsed['database_name']}\n")
            else:
                f.write(f"api_key: {parsed['api_key']}\n")
                f.write(f"database_id: {parsed['database_id']}\n")
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
