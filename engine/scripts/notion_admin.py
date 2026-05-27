"""Notion admin operations for subscope: create or migrate a triage DB.

Merges two previously-separate scripts (notion_setup.py + notion_migrate.py)
into one entry point with subcommands. Both shared the same property
constants and Notion client setup — splitting was extra files for no reason.

Reads `api_key` and `database_id` from `~/.config/subscope/notion.yml` by
default (security fix F1 — never pass NOTION_API_KEY inline on the command
line, since that leaks to ps/proc/shell-history). Falls back to env vars
for CI / non-interactive contexts only.

Subcommands:
  setup    — create a brand-new DB under a parent page (for new users)
  migrate  — add Pattern/State/Fit(LLM) props + backfill rows on an existing DB

Requires:
  pip install -e '.[notion]'

Usage:
  python3 engine/scripts/notion_admin.py setup --parent-page-id <32-char>
  python3 engine/scripts/notion_admin.py migrate            # uses DB ID from notion.yml
  python3 engine/scripts/notion_admin.py migrate --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from subscope.lib import store  # noqa: E402


PATTERN_OPTIONS = [
    {"name": "default", "color": "default"},
    {"name": "stack-audit", "color": "brown"},
    {"name": "churn", "color": "yellow"},
    {"name": "pricing-rage", "color": "red"},
    {"name": "build-vs-buy", "color": "purple"},
    {"name": "rfp-bait", "color": "blue"},
    {"name": "resurrect", "color": "gray"},
    {"name": "rivals", "color": "pink"},
]

STATE_OPTIONS = [
    {"name": "Drafting", "color": "gray"},
    {"name": "Hot", "color": "red"},
    {"name": "Replied", "color": "yellow"},
    {"name": "Won", "color": "green"},
    {"name": "Ignored", "color": "default"},
    {"name": "Dead", "color": "brown"},
]

TIER_OPTIONS = [
    {"name": "T1", "color": "red"},
    {"name": "T2", "color": "orange"},
    {"name": "T3", "color": "gray"},
]


def _read_config() -> dict[str, str]:
    """Read api_key + database_id from ~/.config/subscope/notion.yml.

    Returns whichever fields are present (caller handles missing keys).
    """
    path = store.xdg_config_dir() / "notion.yml"
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def _client(cli_api_key: str | None = None):
    try:
        from notion_client import Client  # type: ignore
    except ImportError:
        print("notion_client not installed. Install with: pip install -e '.[notion]'",
              file=sys.stderr)
        sys.exit(2)
    cfg = _read_config()
    # Priority: explicit CLI arg → config file → env var (CI fallback)
    key = cli_api_key or cfg.get("api_key") or os.environ.get("NOTION_API_KEY")
    if not key:
        print("No Notion API key found. Set one of:\n"
              "  - ~/.config/subscope/notion.yml with 'api_key:' line\n"
              "  - NOTION_API_KEY env var (CI/non-interactive only)",
              file=sys.stderr)
        sys.exit(2)
    if not key.startswith(("secret_", "ntn_")):
        print("warning: key doesn't start with secret_ or ntn_ — double-check the format",
              file=sys.stderr)
    return Client(auth=key)


def create_database(parent_page_id: str) -> tuple[str, str]:
    """Create a fresh DB. Returns (db_id, db_url)."""
    client = _client()

    schema: dict[str, Any] = {
        "Title": {"title": {}},
        "Tier": {"select": {"options": TIER_OPTIONS}},
        "Subreddit": {"rich_text": {}},
        "Score": {"number": {"format": "number"}},
        "Upvotes": {"number": {"format": "number"}},
        "Comments": {"number": {"format": "number"}},
        "Posted": {"date": {}},
        "Pain": {"rich_text": {}},
        "Fit": {"rich_text": {}},
        "URL": {"url": {}},
        "Surfaced on": {"date": {}},
        "Pattern": {"select": {"options": PATTERN_OPTIONS}},
        "State": {"select": {"options": STATE_OPTIONS}},
        "Fit (LLM)": {"number": {"format": "number"}},
        "OP score": {"rich_text": {}},  # karma/age/audience-fit confidence string
    }

    try:
        resp = client.databases.create(
            parent={"type": "page_id", "page_id": parent_page_id},
            title=[{"type": "text", "text": {"content": "subscope surfaces"}}],
            properties=schema,
            icon={"type": "emoji", "emoji": "🔥"},
        )
    except Exception as e:
        print(f"Failed to create database: {e}", file=sys.stderr)
        print("\nCommon causes:", file=sys.stderr)
        print("  - Integration not connected to the parent page", file=sys.stderr)
        print("    (Page → ... → Connections → Add subscope)", file=sys.stderr)
        print("  - Wrong page ID (must be a 32-char page ID, no dashes)", file=sys.stderr)
        sys.exit(2)

    db_id = resp["id"].replace("-", "")
    db_url = resp.get("url", "")
    return db_id, db_url


def migrate(database_id: str, dry_run: bool = False) -> int:
    """Add missing schema properties + backfill. Idempotent."""
    client = _client()

    try:
        db = client.databases.retrieve(database_id=database_id)
    except Exception as e:
        print(f"Failed to read database: {e}", file=sys.stderr)
        return 2

    existing = set(db.get("properties", {}).keys())
    print(f"Existing properties: {sorted(existing)}")

    additions: dict[str, Any] = {}
    if "Pattern" not in existing:
        additions["Pattern"] = {"select": {"options": PATTERN_OPTIONS}}
    if "State" not in existing:
        additions["State"] = {"select": {"options": STATE_OPTIONS}}
    if "Fit (LLM)" not in existing:
        additions["Fit (LLM)"] = {"number": {"format": "number"}}
    if "OP score" not in existing:
        additions["OP score"] = {"rich_text": {}}

    if not additions:
        print("All schema properties already present — nothing to migrate.")
        return 0

    print(f"Would add: {sorted(additions.keys())}")
    if dry_run:
        return 0

    try:
        client.databases.update(database_id=database_id, properties=additions)
    except Exception as e:
        print(f"Update failed: {e}", file=sys.stderr)
        return 2

    print("Schema update applied. Backfilling existing rows...")
    backfilled = _backfill_rows(client, database_id)
    print(f"Backfilled {backfilled} rows (Pattern=default, State=Hot).")
    return 0


def _backfill_rows(client, database_id: str) -> int:
    """Set Pattern='default' + State='Hot' on rows missing those fields.

    Paginates through DB. Rate-limited to 3 req/sec per Notion limits.
    """
    count = 0
    cursor = None
    while True:
        kw: dict[str, Any] = {"database_id": database_id, "page_size": 100}
        if cursor:
            kw["start_cursor"] = cursor
        page = client.databases.query(**kw)
        for row in page.get("results", []):
            props = row.get("properties", {}) or {}
            patches: dict[str, Any] = {}
            if not (props.get("Pattern", {}).get("select") or {}).get("name"):
                patches["Pattern"] = {"select": {"name": "default"}}
            if not (props.get("State", {}).get("select") or {}).get("name"):
                patches["State"] = {"select": {"name": "Hot"}}
            if patches:
                try:
                    client.pages.update(page_id=row["id"], properties=patches)
                    count += 1
                    time.sleep(0.35)  # ~3 req/sec ceiling
                except Exception as e:
                    print(f"  skip row {row['id']}: {e}", file=sys.stderr)
        if not page.get("has_more"):
            break
        cursor = page.get("next_cursor")
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup", help="Create a fresh DB under a Notion parent page")
    s.add_argument(
        "--parent-page-id",
        help="32-char Notion page ID where the DB will be created. "
             "Find it in the page URL: notion.so/Your-Page-<32-char-id>",
    )
    s.add_argument("--dry-run", action="store_true",
                   help="Validate inputs without creating the DB")

    m = sub.add_parser("migrate", help="Add missing schema props + backfill an existing DB")
    m.add_argument(
        "--database-id",
        help="32-char DB ID, no dashes. Default: reads from ~/.config/subscope/notion.yml",
    )
    m.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "setup":
        parent = args.parent_page_id or input(
            "Parent page ID (32 chars from your Notion page URL, no dashes): "
        ).strip().replace("-", "")
        if len(parent) != 32:
            print(f"Parent page ID must be 32 chars, got {len(parent)}.",
                  file=sys.stderr)
            return 2
        if args.dry_run:
            print(f"[dry-run] would create DB under page {parent}")
            return 0
        db_id, db_url = create_database(parent)
        print()
        print("✓ subscope database created")
        print(f"  ID:  {db_id}")
        print(f"  URL: {db_url}")
        print()
        print("Persist this to ~/.config/subscope/notion.yml via:")
        print()
        print(f"  cat <<EOF | python3 -m scripts.write_notion_config")
        print(f"  api_key: <your_secret_xxx>")
        print(f"  database_id: {db_id}")
        print(f"  EOF")
        print()
        print("Then /subscope-run will sync surfaces to your Notion board.")
        return 0

    if args.cmd == "migrate":
        db_id = args.database_id
        if not db_id:
            cfg = _read_config()
            db_id = cfg.get("database_id")
        if not db_id:
            print("No database_id provided and none found in "
                  "~/.config/subscope/notion.yml", file=sys.stderr)
            return 2
        return migrate(db_id, dry_run=args.dry_run)

    return 0


if __name__ == "__main__":
    sys.exit(main())
