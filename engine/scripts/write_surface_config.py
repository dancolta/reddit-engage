#!/usr/bin/env python3
"""Writer for surface.yml — choose how subscope renders the daily list.

Reads YAML-shaped content from stdin (key: value lines). Writes to
~/.config/subscope/surface.yml. Not sensitive enough to warrant 0o600 (no
secrets), but we still write owner-only for consistency.

Schema:
    modes: [table]            # one or more of: table, notion, slack
    default_render: table     # which one /subscope:run prints first

Usage:
    cat <<EOF | python3 -m scripts.write_surface_config
    modes: [table]
    default_render: table
    EOF
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from subscope.lib import store  # noqa: E402


VALID_MODES = {"table", "notion", "slack"}


def main() -> int:
    raw = sys.stdin.read().strip()
    if not raw:
        print("error: empty stdin", file=sys.stderr)
        return 1
    # Parse minimal YAML (key: value, value can be a [list] or string)
    parsed: dict[str, object] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if val.startswith("[") and val.endswith("]"):
            items = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",")]
            items = [v for v in items if v]
            parsed[key] = items
        else:
            parsed[key] = val

    modes = parsed.get("modes")
    if not isinstance(modes, list):
        print("error: 'modes' must be a list, e.g. modes: [table, notion]",
              file=sys.stderr)
        return 1
    unknown = [m for m in modes if m not in VALID_MODES]
    if unknown:
        print(f"error: unknown mode(s) {unknown}; allowed: {sorted(VALID_MODES)}",
              file=sys.stderr)
        return 1

    out_path = store.xdg_config_dir() / "surface.yml"
    fd = os.open(str(out_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write("# subscope surface preferences (where to render daily lists)\n")
            f.write("# Edit this file to change without re-running setup.\n")
            f.write(f"modes: [{', '.join(modes)}]\n")
            if parsed.get("default_render"):
                f.write(f"default_render: {parsed['default_render']}\n")
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
