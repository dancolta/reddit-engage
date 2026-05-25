"""reddit-engage CLI. Python-side does fetch + gate + score + SQLite.

Claude (chat session) is the outer orchestrator per stress-test outcome #1:
- Claude calls Playwright MCP for blog refresh (rarely; only on Dan's signal),
  then passes any new blog post via `blog ingest`.
- Claude invokes `fetch-score`; receives JSON of surfaces.
- Claude calls Notion MCP to sync the daily board.

This script does NOT call any MCP tools. Stdlib + pyyaml only.

Subcommands:
  setup          Bootstrap SQLite, seed configs from YAML
  fetch-score    Fetch deltas, gate, score, mark surfaced, print JSON to stdout
  status         Print last-run summary as JSON
  blog ingest    Upsert blog post(s) from stdin JSON
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from .lib import author_vet, reddit_oauth, reddit_public, score, store


def _resolve_config_dir() -> Path:
    """Resolve user-config directory with dev fallback to repo-local config/.

    Precedence:
      1. XDG/REDDIT_ENGAGE_CONFIG (see store.xdg_config_dir) IF it contains subreddits.yml
      2. Repo-local config/ next to engine/ (dev / fresh-clone workflow)
    """
    xdg = store.xdg_config_dir()
    if (xdg / "subreddits.yml").exists():
        return xdg
    repo_local = Path(__file__).resolve().parent.parent.parent / "config"
    return repo_local


CONFIG_DIR = _resolve_config_dir()


def _load_yaml(name: str) -> dict[str, Any]:
    with open(CONFIG_DIR / name) as f:
        return yaml.safe_load(f) or {}


def _resolve_blog_alias(alias: str, aliases: dict[str, str]) -> str:
    return aliases.get(alias, alias)


def _load_configs() -> dict[str, Any]:
    subs_cfg = _load_yaml("subreddits.yml")
    keywords = _load_yaml("keywords.yml")
    weights = _load_yaml("weights.yml")
    aliases = subs_cfg.get("blog_aliases", {})
    subs = subs_cfg.get("subreddits", [])
    for s in subs:
        s["backing_blogs"] = [_resolve_blog_alias(a, aliases) for a in s.get("backing_blogs", [])]
    return {"subs": subs, "keywords": keywords, "weights": weights}


def _bucket_keywords(bucket: str, kw: dict[str, Any]) -> list[str]:
    return list(set(kw.get("shared", []) + kw.get(bucket, [])))


def cmd_setup() -> None:
    store.bootstrap()
    cfg = _load_configs()
    with store.connect() as conn:
        for s in cfg["subs"]:
            store.upsert_subreddit(conn, s)
        # Seed blog_posts from blog-map.yml so first run has knowledge map.
        blog_map = _load_yaml("blog-map.yml")
        for blog in blog_map.get("blog_posts", []):
            store.upsert_blog_post(conn, {
                "url": blog["url"],
                "title": blog["title"],
                "pain": blog["pain"],
                "saas_replaced": blog["saas_replaced"],
                "persona": blog["persona"],
                "stack": blog["stack"],
                "keywords": blog.get("keywords", []),
            })
    print(json.dumps({"status": "ok", "subs": len(cfg["subs"])}))


def cmd_fetch_score(limit_per_sub: int = 25, daily_cap: int = 15) -> None:
    cfg = _load_configs()
    weights = cfg["weights"]

    with store.connect() as conn:
        run_id = store.start_run(conn)
        blog_posts = store.fetch_blog_posts(conn)

        all_candidates: list[dict[str, Any]] = []
        near_miss_pool: list[dict[str, Any]] = []
        fetch_errors: list[str] = []
        total_fetched = 0
        dropped_counts: dict[str, int] = {}

        for s in cfg["subs"]:
            db_sub = store.get_sub(conn, s["name"])
            if not db_sub:
                store.upsert_subreddit(conn, s)
                db_sub = store.get_sub(conn, s["name"])
            assert db_sub is not None

            last_cursor = db_sub.get("last_cursor")
            try:
                # Prefer OAuth path (10x rate headroom + identity scope); falls
                # back to public JSON automatically when oauth.json missing or
                # PRAW not installed. See reddit_oauth.fetch_delta() docstring.
                posts = reddit_oauth.fetch_delta(s["name"], last_cursor, max_limit=limit_per_sub)
            except Exception as e:
                fetch_errors.append(f"r/{s['name']}: {e}")
                continue

            total_fetched += len(posts)
            if posts:
                store.update_cursor(conn, s["name"], posts[0]["id"])

            bucket_kw = _bucket_keywords(s["bucket"], cfg["keywords"])

            for post in posts:
                if store.already_surfaced(conn, post["id"]):
                    continue

                # Author pre-gate (Phase 1.5): drop low-karma / young / wrong-audience
                # OPs before scoring. Cached 7d to avoid refetching same OP across runs.
                # Degrades open on fetch failure (verdict='pass', reason='fetch_failed').
                vet = author_vet.vet_author(post.get("author", ""), conn=conn)
                if vet["verdict"] == "fail":
                    reason = f"author_vet_{vet['reason']}"
                    dropped_counts[reason] = dropped_counts.get(reason, 0) + 1
                    continue

                blog_matches = score.find_blog_matches(post, blog_posts)

                passes, reason = score.evaluate_gate(
                    post, dict(s, **db_sub), blog_matches, weights, bucket_kw
                )
                post["score_internal"] = score.compute_score(
                    post, dict(s, **db_sub), blog_matches, weights, bucket_kw
                )
                candidate = {
                    "post": post,
                    "sub": dict(s, **db_sub),
                    "blog_matches": blog_matches,
                    "gate_reason": reason,
                }
                if passes:
                    all_candidates.append(candidate)
                else:
                    dropped_counts[reason] = dropped_counts.get(reason, 0) + 1
                    # Backfill pool: only posts that named a specific SaaS
                    # brand AND failed a softer signal (keyword density,
                    # intent). Vendor / negative / no-brand posts are NEVER
                    # backfill-eligible.
                    backfill_disallowed = (
                        score.ABSOLUTE_REJECT_REASONS
                        | {"tier1_post_age", "tier2_post_age",
                           "tier1_no_saas_brand", "tier2_no_saas_brand"}
                    )
                    if reason not in backfill_disallowed:
                        near_miss_pool.append(candidate)

        # Daily mixing rule per plan 2f, with minimum-floor backfill
        selected = _select_daily(all_candidates, near_miss_pool, weights, daily_cap)

        # Persist. Each surface is isolated so one bad row does not kill the run.
        persist_errors: list[str] = []
        kept_for_output: list[dict[str, Any]] = []
        for s in selected:
            post = s["post"]
            sub_row = s["sub"]
            try:
                store.insert_post(conn, post)
                store.update_score(conn, post["id"], post["score_internal"])
                for m in s["blog_matches"]:
                    store.record_blog_ref(
                        conn, post["id"], m["url"], m["match_score"], m["matched_keywords"]
                    )
                store.mark_surfaced(conn, post["id"], run_id, sub_row["tier"])
            except Exception as e:
                persist_errors.append(f"{post.get('id', '?')}: {e}")
                continue
            s["pain_summary"] = _pain_summary(post, s["blog_matches"])
            s["fit_summary"] = _fit_summary(sub_row, s["blog_matches"])
            s["score_internal"] = post["score_internal"]
            kept_for_output.append(s)
        selected = kept_for_output

        all_notes = fetch_errors + [f"persist:{e}" for e in persist_errors]
        notes = "; ".join(all_notes) if all_notes else ""
        store.finish_run(conn, run_id, total_fetched, len(selected), notes)

    from .lib import output as out_mod  # local import to avoid hard dep at setup time
    payload = {
        "run_id": run_id,
        "fetched": total_fetched,
        "surfaced": len(selected),
        "dropped_counts": dropped_counts,
        "notes": notes,
        "surfaces": out_mod.render_json_payload(selected),
        "inline_markdown": out_mod.render(selected, notes, dropped_counts),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _select_daily(candidates: list[dict[str, Any]], near_miss_pool: list[dict[str, Any]],
                  weights: dict[str, Any], daily_cap: int) -> list[dict[str, Any]]:
    """Pick daily surfaces. Hard ceiling, per-sub caps, AND minimum-floor backfill.

    Order of priority:
      1. Gate-passing Tier 1 posts (top N by score, capped per sub)
      2. Gate-passing Tier 2 posts (top by score, capped per sub)
      3. If still under `minimum`, backfill from near-miss pool by score
         (still age-gated, just below the keyword bar or other soft signal)
    """
    out_cfg = weights.get("daily_output", {})
    cap = int(out_cfg.get("hard_ceiling", daily_cap))
    minimum = int(out_cfg.get("minimum", 0))
    t1_per_sub = int(out_cfg.get("tier1_per_sub_cap", 2))
    t2_per_sub = int(out_cfg.get("tier2_per_sub_cap", 1))

    # Deduplicate by (subreddit, title) before selection. Two posts in
    # /new with identical titles from the same sub almost always means
    # a cross-post or duplicate by the same OP. Keep the higher-scoring one.
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for c in candidates:
        key = (c["sub"]["name"].lower(), c["post"]["title"].strip().lower())
        prev = by_key.get(key)
        if prev is None or c["post"]["score_internal"] > prev["post"]["score_internal"]:
            by_key[key] = c
    candidates = list(by_key.values())

    t1_pool = [c for c in candidates if c["sub"]["tier"] == 1]
    t2_pool = [c for c in candidates if c["sub"]["tier"] == 2]
    t1_pool.sort(key=lambda c: c["post"]["score_internal"], reverse=True)
    t2_pool.sort(key=lambda c: c["post"]["score_internal"], reverse=True)

    chosen: list[dict[str, Any]] = []
    sub_counts: dict[str, int] = {}
    for c in t1_pool:
        if len(chosen) >= cap:
            break
        name = c["sub"]["name"]
        if sub_counts.get(name, 0) >= t1_per_sub:
            continue
        chosen.append(c)
        sub_counts[name] = sub_counts.get(name, 0) + 1

    for c in t2_pool:
        if len(chosen) >= cap:
            break
        name = c["sub"]["name"]
        if sub_counts.get(name, 0) >= t2_per_sub:
            continue
        chosen.append(c)
        sub_counts[name] = sub_counts.get(name, 0) + 1

    # Minimum-floor backfill: if still under `minimum`, pull from the near-miss pool
    # (posts that failed a soft signal like keyword density, ranked by computed score).
    # Per-sub caps still apply so backfill cannot concentrate in one sub.
    if minimum > 0 and len(chosen) < minimum and near_miss_pool:
        near_miss_pool.sort(key=lambda c: c["post"]["score_internal"], reverse=True)
        for c in near_miss_pool:
            if len(chosen) >= min(cap, minimum):
                break
            name = c["sub"]["name"]
            sub_cap = t1_per_sub if c["sub"]["tier"] == 1 else t2_per_sub
            if sub_counts.get(name, 0) >= sub_cap:
                continue
            c["backfilled"] = True
            chosen.append(c)
            sub_counts[name] = sub_counts.get(name, 0) + 1

    return chosen


def _pain_summary(post: dict[str, Any], blog_matches: list[dict[str, Any]]) -> str:
    if blog_matches:
        kws = blog_matches[0].get("matched_keywords", [])
        if kws:
            return f"Matches blog keywords: {', '.join(kws[:4])}"
    title = post.get("title", "")
    return title[:120]


def _fit_summary(sub_row: dict[str, Any], blog_matches: list[dict[str, Any]]) -> str:
    sat = sub_row.get("saturation")
    base = f"r/{sub_row['name']}"
    if sub_row["tier"] == 1:
        base += " is a Tier 1 daily-scan sub"
    elif sat == "wide_open":
        base += " (wide-open: low competitor density)"
    elif sat == "high":
        base += " (high saturation: gate verified)"
    if blog_matches:
        return f"{base}, backed by {blog_matches[0]['title']}"
    return f"{base}. No direct blog backing, topic-adjacent reply."


def cmd_status() -> None:
    with store.connect() as conn:
        last = store.stats_last_run(conn)
    print(json.dumps({
        "last_run": last,
        "config_dir": str(CONFIG_DIR),
        "db_path": str(store.db_path()),
    }, default=str, indent=2))


def cmd_blog_ingest() -> None:
    """Read blog post JSON from stdin (orchestrator-provided), upsert into blog_posts."""
    payload = json.load(sys.stdin)
    posts = payload if isinstance(payload, list) else [payload]
    with store.connect() as conn:
        for blog in posts:
            store.upsert_blog_post(conn, blog)
    print(json.dumps({"status": "ok", "ingested": len(posts)}))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="reddit-engage")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("setup", help="Bootstrap DB + load configs")
    fs = sub.add_parser("fetch-score", help="Fetch deltas, gate, score, surface")
    fs.add_argument("--limit-per-sub", type=int, default=25)
    fs.add_argument("--daily-cap", type=int, default=15)
    sub.add_parser("status", help="Print last-run status as JSON")

    blog = sub.add_parser("blog", help="Blog map operations").add_subparsers(dest="blogcmd", required=True)
    blog.add_parser("ingest", help="Upsert blog post(s) from stdin JSON")

    args = parser.parse_args(argv)

    if args.cmd == "setup":
        cmd_setup()
    elif args.cmd == "fetch-score":
        cmd_fetch_score(args.limit_per_sub, args.daily_cap)
    elif args.cmd == "status":
        cmd_status()
    elif args.cmd == "blog" and args.blogcmd == "ingest":
        cmd_blog_ingest()


if __name__ == "__main__":
    main()
