"""One-shot Notion DB schema migration for reddit-engage.

Adds three properties to the existing reddit-engage Notion database:
  - Pattern (select)        with options matching VALID_MODES
  - State (select)          with: Drafting, Hot, Replied, Won, Ignored, Dead
  - Fit (LLM) (number 0-10) the classifier's fit_score

Backfills existing rows: any row missing Pattern gets 'default'; missing
State gets 'Hot'. Idempotent — re-running detects existing properties
and skips additions.

Requires:
  pip install -e '.[notion]'

Usage:
  NOTION_API_KEY=secret_xxx python3 engine/scripts/notion_migrate.py \\
      --database-id <32-char id>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any


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


def _client():
    try:
        from notion_client import Client  # type: ignore
    except ImportError:
        print("notion_client not installed. Install with: pip install -e '.[notion]'",
              file=sys.stderr)
        sys.exit(2)
    key = os.environ.get("NOTION_API_KEY")
    if not key:
        print("NOTION_API_KEY env var not set", file=sys.stderr)
        sys.exit(2)
    return Client(auth=key)


def migrate(database_id: str, dry_run: bool = False) -> int:
    """Returns 0 success, non-zero on failure."""
    client = _client()

    # Fetch current schema
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

    if not additions:
        print("All 3 properties already present — nothing to migrate.")
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
        kw = {"database_id": database_id, "page_size": 100}
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--database-id", required=True, help="Notion DB ID (32 chars, no dashes)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sys.exit(migrate(args.database_id, args.dry_run))


if __name__ == "__main__":
    main()
