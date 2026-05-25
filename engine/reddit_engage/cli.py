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

from .lib import author_vet, classify, reddit_oauth, reddit_public, score, store


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


def _load_yaml(name: str, optional: bool = False) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists() and optional:
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _resolve_blog_alias(alias: str, aliases: dict[str, str]) -> str:
    return aliases.get(alias, alias)


# Valid pattern modes. Adding a new pattern? Add an entry here + drop a
# config/keywords-<mode>.yml + emoji prefix in PATTERN_EMOJI below.
VALID_MODES = {
    "default", "stack-audit", "churn", "pricing-rage",
    "build-vs-buy", "rfp-bait", "resurrect", "rivals",
}

PATTERN_EMOJI = {
    "default": "",
    "stack-audit": "🧱",
    "churn": "⚡",
    "pricing-rage": "🔥",
    "build-vs-buy": "⚖️",
    "rfp-bait": "🤝",
    "resurrect": "🪦",
    "rivals": "🥷",
}


def _load_configs(mode: str = "default") -> dict[str, Any]:
    """Load subs + mode-specific keywords + mode-specific weight overrides.

    Mode override files (`keywords-<mode>.yml`, `weights-<mode>.yml`) are
    optional. When present, they shadow the base files entirely (not merge —
    pattern-specific gates can be radically different from default).
    """
    if mode not in VALID_MODES:
        raise ValueError(f"unknown --mode {mode!r}; valid: {sorted(VALID_MODES)}")

    subs_cfg = _load_yaml("subreddits.yml")
    base_kw = _load_yaml("keywords.yml")
    base_w = _load_yaml("weights.yml")

    # Mode-specific overrides
    if mode != "default":
        mode_kw = _load_yaml(f"keywords-{mode}.yml", optional=True)
        mode_w = _load_yaml(f"weights-{mode}.yml", optional=True)
        keywords = mode_kw or base_kw
        weights = {**base_w, **mode_w} if mode_w else base_w
    else:
        keywords = base_kw
        weights = base_w

    aliases = subs_cfg.get("blog_aliases", {})
    subs = subs_cfg.get("subreddits", [])
    for s in subs:
        s["backing_blogs"] = [_resolve_blog_alias(a, aliases) for a in s.get("backing_blogs", [])]
    return {"subs": subs, "keywords": keywords, "weights": weights, "mode": mode}


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


def cmd_fetch_score(
    limit_per_sub: int = 25,
    daily_cap: int = 15,
    no_cool: bool = False,
    cool_minutes: int = 30,
    mode: str = "default",
    rivals_brand: str | None = None,
) -> None:
    """Run the surface pipeline for a specific pattern mode.

    Modes (see VALID_MODES):
      default        — general pain + named SaaS
      stack-audit    — OPs listing many tools, asking to consolidate
      churn          — switching/canceling + vendor anchor
      pricing-rage   — price-hike threads (auto --no-cool)
      build-vs-buy   — debates with numbers
      rfp-bait       — "A vs B vs C" comparison threads
      resurrect      — 6-18mo old high-quality threads
      rivals         — competitor mention digest (requires rivals_brand)

    Each mode optionally loads `config/keywords-<mode>.yml` and
    `config/weights-<mode>.yml`. Missing mode-config falls back to default.
    """
    cfg = _load_configs(mode=mode)
    weights = cfg["weights"]
    # pricing-rage is time-sensitive — auto-disable cooling unless overridden
    if mode == "pricing-rage" and not no_cool:
        no_cool = True
    # rivals requires brand argument
    if mode == "rivals" and not rivals_brand:
        raise ValueError("--rivals-brand is required when --mode=rivals")

    with store.connect() as conn:
        run_id = store.start_run(conn)
        # Promote mature drafts BEFORE this run so today's surfaces compete
        # cleanly. Decay old surfaces at the same time.
        promoted = store.flush_cooling_queue(conn, cool_minutes=cool_minutes)
        decayed = store.decay_old_surfaces(conn, days=14)
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
                    # Optional Phase 2 LLM classifier: only fires on regex-gate
                    # survivors (~5% of fetched volume) so cost stays bounded.
                    # If provider disabled / fails, classifier=None and the post
                    # surfaces on regex strength alone (graceful degradation).
                    verdict = classify.classify(post)
                    if verdict is not None:
                        post["classifier"] = verdict
                        # Vendor content slipped through regex? Drop here.
                        if verdict["intent"] == "vendor_content":
                            reason = "classifier_vendor"
                            dropped_counts[reason] = dropped_counts.get(reason, 0) + 1
                            continue
                        # Boost score by LLM fit_score (0-10 → 0-30 bonus).
                        post["score_internal"] = post["score_internal"] + (verdict["fit_score"] * 3)
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
                # Cooling queue: surfaces land 'drafting' (held cool_minutes)
                # unless --no-cool is set. Notion sync flushes only 'hot' rows.
                surface_state = "hot" if no_cool else "drafting"
                store.mark_surfaced(conn, post["id"], run_id, sub_row["tier"],
                                    state=surface_state)
            except Exception as e:
                persist_errors.append(f"{post.get('id', '?')}: {e}")
                continue
            s["pain_summary"] = _pain_summary(post, s["blog_matches"])
            s["fit_summary"] = _fit_summary(sub_row, s["blog_matches"])
            s["score_internal"] = post["score_internal"]
            s["pattern"] = mode
            s["pattern_emoji"] = PATTERN_EMOJI.get(mode, "")
            kept_for_output.append(s)
        selected = kept_for_output

        all_notes = fetch_errors + [f"persist:{e}" for e in persist_errors]
        notes = "; ".join(all_notes) if all_notes else ""
        store.finish_run(conn, run_id, total_fetched, len(selected), notes)

    from .lib import output as out_mod
    payload = {
        "run_id": run_id,
        "mode": mode,
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
    fs.add_argument("--no-cool", action="store_true",
                    help="Skip cooling queue — surfaces immediately visible "
                         "(use for time-sensitive patterns like pricing-rage)")
    fs.add_argument("--cool-minutes", type=int, default=30,
                    help="Cooling queue hold duration (default 30)")
    fs.add_argument("--mode", choices=sorted(VALID_MODES), default="default",
                    help="Pattern mode — gate and keywords change per pattern")
    fs.add_argument("--rivals-brand", type=str, default=None,
                    help="Brand name to track (required if --mode=rivals)")

    ov = sub.add_parser("op-vet", help="Score a Reddit OP profile (utility, one-shot)")
    ov.add_argument("username", type=str)

    sub.add_parser("status", help="Print last-run status as JSON")

    blog = sub.add_parser("blog", help="Blog map operations").add_subparsers(dest="blogcmd", required=True)
    blog.add_parser("ingest", help="Upsert blog post(s) from stdin JSON")

    args = parser.parse_args(argv)

    if args.cmd == "setup":
        cmd_setup()
    elif args.cmd == "fetch-score":
        cmd_fetch_score(
            args.limit_per_sub, args.daily_cap,
            no_cool=args.no_cool, cool_minutes=args.cool_minutes,
            mode=args.mode, rivals_brand=args.rivals_brand,
        )
    elif args.cmd == "op-vet":
        cmd_op_vet(args.username)
    elif args.cmd == "status":
        cmd_status()
    elif args.cmd == "blog" and args.blogcmd == "ingest":
        cmd_blog_ingest()


def cmd_op_vet(username: str) -> None:
    """Standalone OP profile scorer. Outputs JSON: {karma, age_days,
    sub_breakdown_top, verdict, reason}. Used by `/reddit-engage:op-vet`."""
    with store.connect() as conn:
        result = author_vet.vet_author(username, conn=conn)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
