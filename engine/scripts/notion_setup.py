"""One-shot Notion database creator for new reddit-engage users.

Plug-and-play: given a Notion API key + a parent page ID, this script
creates a fresh database with the full reddit-engage schema (all 13
properties, all select options, emoji-tagged Pattern values). Outputs
the new database ID for the user to drop into oauth-style notion.yml.

Difference from notion_migrate.py:
  - notion_migrate.py:  modify an EXISTING DB (add 3 missing properties + backfill)
  - notion_setup.py:    create a NEW DB from scratch (this script)

Most public users will use this. Migration is for the case where you
already had a reddit-engage DB before the Phase 4 schema changes.

Requires:
  pip install -e '.[notion]'

Usage:
  NOTION_API_KEY=secret_xxx python3 engine/scripts/notion_setup.py \\
      --parent-page-id <32-char Notion page ID where DB will live>

  # Or interactive: prompts for both if env vars missing
  python3 engine/scripts/notion_setup.py

The integration's "Connections" permission must include the parent page
BEFORE you run this — see docs/setup-notion.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
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

TIER_OPTIONS = [
    {"name": "T1", "color": "red"},
    {"name": "T2", "color": "orange"},
    {"name": "T3", "color": "gray"},
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
        key = input("Notion API key (from https://www.notion.so/profile/integrations): ").strip()
    if not key.startswith(("secret_", "ntn_")):
        print("Warning: key doesn't start with secret_ or ntn_ — double-check the format",
              file=sys.stderr)
    return Client(auth=key)


def create_database(parent_page_id: str) -> str:
    """Create the DB. Returns the new database ID."""
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
    }

    try:
        resp = client.databases.create(
            parent={"type": "page_id", "page_id": parent_page_id},
            title=[{"type": "text", "text": {"content": "reddit-engage surfaces"}}],
            properties=schema,
            icon={"type": "emoji", "emoji": "🔥"},
        )
    except Exception as e:
        print(f"Failed to create database: {e}", file=sys.stderr)
        print("\nCommon causes:", file=sys.stderr)
        print("  - Integration not connected to the parent page", file=sys.stderr)
        print("    (Page → ... → Connections → Add reddit-engage)", file=sys.stderr)
        print("  - Wrong page ID (must be a 32-char page ID, no dashes)", file=sys.stderr)
        sys.exit(2)

    db_id = resp["id"].replace("-", "")
    db_url = resp.get("url", "")
    return db_id, db_url


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--parent-page-id",
        help="32-char Notion page ID where the DB will be created. "
             "Get it from the page URL: notion.so/Your-Page-<32-char-id>",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate inputs without creating the DB")
    args = parser.parse_args()

    parent = args.parent_page_id or input(
        "Parent page ID (from your Notion page URL, the last 32 chars without dashes): "
    ).strip().replace("-", "")
    if len(parent) != 32:
        print(f"Parent page ID must be 32 chars, got {len(parent)}. "
              "Open your Notion page and copy the ID from the URL.",
              file=sys.stderr)
        sys.exit(2)

    if args.dry_run:
        print(f"[dry-run] would create DB under page {parent}")
        return

    db_id, db_url = create_database(parent)
    print()
    print("✓ reddit-engage database created")
    print(f"  ID:  {db_id}")
    print(f"  URL: {db_url}")
    print()
    print("Drop this into your config:")
    print()
    print(f"  cat > ~/.config/reddit-engage/notion.yml <<'EOF'")
    print(f"  api_key: $NOTION_API_KEY")
    print(f"  database_id: {db_id}")
    print(f"  EOF")
    print(f"  chmod 600 ~/.config/reddit-engage/notion.yml")
    print()
    print("Then /reddit-engage:run will sync surfaces to your Notion board.")


if __name__ == "__main__":
    main()
