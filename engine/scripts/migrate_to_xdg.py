"""One-shot migration: copy legacy in-project SQLite DB to XDG data dir.

Old path: <project-root>/db/subseek.sqlite
New path: $SUBSEEK_DATA or $XDG_DATA_HOME/subseek or ~/.local/share/subseek/subseek.sqlite

Behavior:
  - If XDG DB already exists → skip (no overwrite).
  - If legacy DB missing → skip.
  - Otherwise: copy + verify row counts match + rename source to .pre-xdg-bak.

Idempotent. Safe to re-run. Exits non-zero on row-count mismatch.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path


def count_rows(db_file: Path) -> dict[str, int]:
    """Return {table_name: row_count} for every user table."""
    counts: dict[str, int] = {}
    with sqlite3.connect(str(db_file)) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for (tname,) in rows:
            counts[tname] = conn.execute(f"SELECT COUNT(*) FROM {tname}").fetchone()[0]
    return counts


def migrate(project_root: Path, dry_run: bool = False) -> int:
    """Returns exit code: 0 success/skip, 1 row-count mismatch, 2 other failure."""
    from subseek.lib import store

    legacy_db = project_root / "db" / "subseek.sqlite"
    xdg_db = store.db_path()  # default = XDG path

    print(f"Legacy path : {legacy_db}")
    print(f"XDG path    : {xdg_db}")

    if xdg_db.exists():
        print("XDG DB already exists. Skipping (no overwrite).")
        return 0

    if not legacy_db.exists():
        print("Legacy DB not found. Nothing to migrate.")
        return 0

    if dry_run:
        print("[dry-run] would copy legacy → XDG and verify row counts")
        return 0

    # Copy + verify
    xdg_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy_db, xdg_db)
    src_counts = count_rows(legacy_db)
    dst_counts = count_rows(xdg_db)

    if src_counts != dst_counts:
        print("Row-count mismatch after copy:", file=sys.stderr)
        print(f"  source: {src_counts}", file=sys.stderr)
        print(f"  dest:   {dst_counts}", file=sys.stderr)
        # Roll back: remove the bad copy so a re-run doesn't think it succeeded.
        try:
            xdg_db.unlink()
        except OSError:
            pass
        return 1

    print(f"Copied + verified: {sum(src_counts.values())} rows across {len(src_counts)} tables")

    # Rename source so future runs don't re-trigger
    backup = legacy_db.with_suffix(".sqlite.pre-xdg-bak")
    legacy_db.rename(backup)
    print(f"Source renamed → {backup}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parent.parent.parent,
        help="Repo root containing the legacy db/ directory (default: auto-detect)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print actions without copying")
    args = parser.parse_args()
    sys.exit(migrate(args.project_root, args.dry_run))


if __name__ == "__main__":
    main()
