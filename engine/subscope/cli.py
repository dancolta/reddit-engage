"""subscope CLI. Python-side does fetch + gate + score + SQLite.

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

from .lib import author_vet, classify, discover, enrich, reddit, score, slack, store


def _resolve_config_dir() -> Path:
    """Resolve user-config directory with dev fallback to repo-local config/.

    Precedence:
      1. XDG/SUBSCOPE_CONFIG (see store.xdg_config_dir) IF it contains subreddits.yml
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
        # blog-map.yml is OPTIONAL — many users won't have a blog.
        blog_map = _load_yaml("blog-map.yml", optional=True)
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


def cmd_orient() -> None:
    """Print the locked welcome + fork message for first-launch UX.

    Voice locked per ui-ux Phase 9.5 redesign: 3-question routing REPLACES
    the preset menu (validated by all 4 research agents — generic preset
    alone produces 3/10 ICP-match per surface, 3-question routing reaches
    5-7/10). Preset becomes the 'type preset to skip' escape hatch.

    Operational language only ("targeting", "subreddits", "config") — no
    profiling vocabulary ("ICP", "profile", "audience") that signals lead-
    gen tooling.
    """
    welcome = (
        "subscope installed. This runs locally in your Claude session and "
        "posts nothing without you.\n"
    )
    fork = (
        "\nThree quick questions so /subscope-run targets the right "
        "subreddits — about 60 seconds.\n\n"
        "  Start with: /subscope-onboard\n\n"
        "Other paths:\n"
        "  /subscope-onboard preset  — skip questions, pick a generic lane (~30s)\n"
        "  /subscope-profile         — 8-question deep interview (~12min, "
        "sharper targeting)\n"
    )
    print(welcome + fork)


def _is_backfill_eligible(reason: str, post: dict[str, Any]) -> bool:
    """Freshness/backfill pool contract: a near-miss qualifies ONLY if it named
    a specific SaaS brand AND failed a softer signal (keyword density, intent).

    The brand requirement is ENFORCED here in code, not inferred from the gate.
    The tier gates (score._tier1_gate / _tier2_gate) check keyword_density BEFORE
    the no_saas_brand check and short-circuit on first failure, so a post with no
    keywords AND no brand carries the soft reason `tier1_keyword_density`, not
    `tier1_no_saas_brand`. Without this re-check, brandless posts leak into the
    pool and get surfaced by the freshness floor / minimum backfill when nothing
    real passes the gate, which reads as off-intent noise.
    """
    backfill_disallowed = (
        score.ABSOLUTE_REJECT_REASONS
        | {"tier1_post_age", "tier2_post_age",
           "tier1_no_saas_brand", "tier2_no_saas_brand"}
    )
    if reason in backfill_disallowed:
        return False
    return score.names_specific_saas(post.get("title", ""), post.get("body", ""))


def cmd_fetch_score(
    limit_per_sub: int = 25,
    daily_cap: int | None = None,           # None = read from weights.yml pattern_caps
    no_cool: bool = False,
    cool_minutes: int | None = None,        # None = read from weights.yml
    mode: str = "default",
    no_slack: bool = False,
    max_surfaces: int | None = None,        # power-user override, see weights.yml note
    no_enrich: bool = False,                # kill switch for DFS + Firecrawl cache reads
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
      rivals         — competitor mention digest (uses brand_anchor from config)

    Each mode optionally loads `config/keywords-<mode>.yml` and
    `config/weights-<mode>.yml`. Missing mode-config falls back to default.
    """
    cfg = _load_configs(mode=mode)
    weights = cfg["weights"]

    # Plumb the --no-enrich flag through the module-level toggle so every
    # downstream cache lookup honors it (mirrors set_disabled in classify.py).
    enrich.set_disabled(no_enrich)
    # Resolve pattern-specific caps + cooling from weights.yml if not overridden
    out_cfg = weights.get("daily_output", {})
    if daily_cap is None:
        pattern_caps = out_cfg.get("pattern_caps") or {}
        daily_cap = int(pattern_caps.get(mode, out_cfg.get("default_target", 10)))
    if cool_minutes is None:
        cool_cfg = weights.get("cooling", {})
        if mode == "pricing-rage":
            cool_minutes = int(cool_cfg.get("pricing_rage_minutes", 0))
        elif mode == "resurrect":
            cool_minutes = int(cool_cfg.get("resurrect_minutes", 30))
        else:
            cool_minutes = int(cool_cfg.get("default_minutes", 15))
    # pricing-rage = time-sensitive: zero cooling
    if mode == "pricing-rage" and not no_cool and cool_minutes == 0:
        no_cool = True

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
                # Public-JSON-only fetcher. See reddit.fetch_delta() docstring.
                posts = reddit.fetch_delta(s["name"], last_cursor, max_limit=limit_per_sub)
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
                vet = author_vet.vet_author(post.get("author", ""), conn=conn, weights=weights)
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
                    "vet": vet,
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
                    # Backfill pool: only posts that named a specific SaaS brand
                    # AND failed a softer signal. Brand check is enforced in
                    # _is_backfill_eligible (the gate short-circuits before the
                    # brand check, so reason alone cannot be trusted here).
                    if _is_backfill_eligible(reason, post):
                        near_miss_pool.append(candidate)

        # Phase B enrichment: pure cache-read augmentation on the gate-pass set
        # BEFORE selection so any link_context can inform the inline table.
        # No-op when no creds are present (default state) or when --no-enrich.
        enrich.augment_scores(all_candidates, conn)

        # Daily mixing rule per plan 2f, with minimum-floor backfill.
        # Power-user override: --max-surfaces N bypasses weights.yml hard_ceiling.
        selected = _select_daily(all_candidates, near_miss_pool, weights, daily_cap,
                                 max_surfaces=max_surfaces)
        if max_surfaces and max_surfaces > 12:
            _emit_max_surfaces_warning(max_surfaces)

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
        "inline_table": out_mod.render_table(selected, dropped_counts),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    # Optional Slack push: silent no-op when no webhook configured. Never
    # blocks the run; failure is logged to stderr only.
    if not no_slack:
        slack.notify_if_configured(payload)


def _select_daily(candidates: list[dict[str, Any]], near_miss_pool: list[dict[str, Any]],
                  weights: dict[str, Any], daily_cap: int,
                  max_surfaces: int | None = None) -> list[dict[str, Any]]:
    """Pick daily surfaces. Hard ceiling, per-sub caps, freshness floor, and
    minimum-floor backfill.

    Order of priority:
      1. Gate-passing Tier 1 posts (top N by score, capped per sub)
      2. Gate-passing Tier 2 posts (top by score, capped per sub)
      3. Freshness floor: auto-promote any near-miss post < `freshness_floor.max_age_hours`
         old, up to `freshness_floor.max_promoted`. Bypasses per-sub caps because
         freshness IS the signal. Tagged `freshness_promoted=True` for telemetry.
      4. If still under `minimum`, backfill from remaining near-miss pool by score.
         During backfill ONLY, per-sub caps relax by `backfill_sub_cap_bonus`
         so a sub that already supplied a hot Tier-2 surface can still backfill.

    `max_surfaces` is the power-user override (--max-surfaces flag). Beats
    weights.yml hard_ceiling when set. Per-sub caps still apply on Tier 1/Tier 2
    selection — the user can pull from more SUBS, not more posts per sub
    (quality guardrail). Freshness + backfill phases relax this.
    """
    out_cfg = weights.get("daily_output", {})
    cap = max_surfaces or int(out_cfg.get("hard_ceiling", daily_cap))
    minimum = int(out_cfg.get("minimum", 0))
    t1_per_sub = int(out_cfg.get("tier1_per_sub_cap", 2))
    t2_per_sub = int(out_cfg.get("tier2_per_sub_cap", 1))
    backfill_bonus = int(out_cfg.get("backfill_sub_cap_bonus", 0))

    fresh_cfg = weights.get("freshness_floor") or {}
    fresh_enabled = bool(fresh_cfg.get("enabled", False))
    fresh_max_age_s = int(fresh_cfg.get("max_age_hours", 24)) * 3600
    fresh_max_promoted = int(fresh_cfg.get("max_promoted", 3))

    now_ts = int(time.time())

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
    chosen_ids: set[str] = set()

    def _take(c: dict[str, Any]) -> None:
        chosen.append(c)
        chosen_ids.add(c["post"]["id"])
        sub_counts[c["sub"]["name"]] = sub_counts.get(c["sub"]["name"], 0) + 1

    for c in t1_pool:
        if len(chosen) >= cap:
            break
        name = c["sub"]["name"]
        if sub_counts.get(name, 0) >= t1_per_sub:
            continue
        _take(c)

    for c in t2_pool:
        if len(chosen) >= cap:
            break
        name = c["sub"]["name"]
        if sub_counts.get(name, 0) >= t2_per_sub:
            continue
        _take(c)

    # Phase 3: Freshness floor. Auto-promote near-miss posts younger than the
    # configured window. Bypasses per-sub caps because freshness IS the signal
    # (a 2h-old post that fails keyword density is often a real ICP signal
    # the keyword set just didn't anticipate yet).
    if fresh_enabled and near_miss_pool and len(chosen) < cap:
        fresh_candidates = [
            c for c in near_miss_pool
            if c["post"]["id"] not in chosen_ids
            and (now_ts - int(c["post"].get("created_utc", 0))) < fresh_max_age_s
        ]
        fresh_candidates.sort(
            key=lambda c: int(c["post"].get("created_utc", 0)),
            reverse=True,
        )
        promoted = 0
        for c in fresh_candidates:
            if promoted >= fresh_max_promoted or len(chosen) >= cap:
                break
            c["freshness_promoted"] = True
            _take(c)
            promoted += 1

    # Phase 4: Minimum-floor backfill. If still under `minimum`, pull from the
    # near-miss pool by score. Per-sub caps relax by `backfill_sub_cap_bonus`
    # so a sub that supplied a hot Tier 2 surface (consuming its quota) can
    # still backfill. Without this, scans on narrow profiles return <minimum
    # surfaces even when good candidates exist.
    if minimum > 0 and len(chosen) < minimum and near_miss_pool:
        remaining = [
            c for c in near_miss_pool if c["post"]["id"] not in chosen_ids
        ]
        remaining.sort(key=lambda c: c["post"]["score_internal"], reverse=True)
        for c in remaining:
            if len(chosen) >= min(cap, minimum):
                break
            name = c["sub"]["name"]
            base_cap = t1_per_sub if c["sub"]["tier"] == 1 else t2_per_sub
            if sub_counts.get(name, 0) >= base_cap + backfill_bonus:
                continue
            c["backfilled"] = True
            _take(c)

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
        enrichment_state = enrich.status(conn)
    print(json.dumps({
        "last_run": last,
        "config_dir": str(CONFIG_DIR),
        "db_path": str(store.db_path()),
        "llm": classify.status(),
        "slack": slack.status(),
        "enrichment": enrichment_state,
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
    parser = argparse.ArgumentParser(prog="subscope")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("setup", help="Bootstrap DB + load configs")
    sub.add_parser("orient", help="Print first-launch welcome + fork message")
    fs = sub.add_parser("fetch-score", help="Fetch deltas, gate, score, surface")
    fs.add_argument("--limit-per-sub", type=int, default=25)
    fs.add_argument("--daily-cap", type=int, default=None,
                    help="Override pattern-specific cap (default: read from weights.yml pattern_caps)")
    fs.add_argument("--no-cool", action="store_true",
                    help="Skip cooling queue — surfaces immediately visible "
                         "(use for time-sensitive patterns like pricing-rage)")
    fs.add_argument("--cool-minutes", type=int, default=None,
                    help="Cooling queue hold duration (default: read from weights.yml cooling)")
    fs.add_argument("--mode", choices=sorted(VALID_MODES), default="default",
                    help="Pattern mode — gate and keywords change per pattern")
    fs.add_argument("--no-enrich", action="store_true",
                    help="Disable DataForSEO + Firecrawl cache reads for this run.")
    fs.add_argument("--no-slack", action="store_true",
                    help="Skip Slack notification even if webhook is configured")
    fs.add_argument("--max-surfaces", type=int, default=None,
                    help="POWER USER: surface up to N items (default: weights.yml hard_ceiling=12). "
                         "Reddit API is fine with the volume; review fatigue is the actual risk. "
                         "Plan ~1 min per surface. To raise the per-profile sub ceiling above 13 "
                         "total, edit tier1_subs_max / tier2_subs_max in weights.yml.")

    ov = sub.add_parser("op-vet", help="Score a Reddit OP profile (utility, one-shot)")
    ov.add_argument("username", type=str)

    dc = sub.add_parser("discover", help="Live subreddit discovery from interview answers")
    dc.add_argument("--answers-json", type=str, required=True,
                    help="JSON object with keys what_offering, who_to_reach, pain_quote. "
                         "Pass '-' or '/dev/stdin' to read from stdin (avoids shell quoting issues).")
    dc.add_argument("--homepage", type=str, default="",
                    help="User homepage URL (for cache lookups: Firecrawl scrape + DFS competitors)")
    dc.add_argument("--vertical", type=str, default=None,
                    help="Optional vertical clarifier value (set on Tier-A retry)")
    dc.add_argument("--competitors", type=str, default="",
                    help="Comma-separated competitor brands or domains. Used by the "
                         "engine to generate 'replacing X' and 'X alternative' queries. "
                         "Pass these from the skill when Claude found them via WebFetch.")
    dc.add_argument("--fresh-window-hours", type=int, default=None,
                    help="Buyer-activity freshness window in hours. Default 168 (7 days) "
                         "for onboarding discovery. Pass 720 on the 'broaden' clarifier path.")

    sub.add_parser("status", help="Print last-run status as JSON")

    blog = sub.add_parser("blog", help="Blog map operations").add_subparsers(dest="blogcmd", required=True)
    blog.add_parser("ingest", help="Upsert blog post(s) from stdin JSON")

    args = parser.parse_args(argv)

    if args.cmd == "setup":
        cmd_setup()
    elif args.cmd == "orient":
        cmd_orient()
    elif args.cmd == "fetch-score":
        cmd_fetch_score(
            args.limit_per_sub, args.daily_cap,
            no_cool=args.no_cool, cool_minutes=args.cool_minutes,
            mode=args.mode, no_slack=args.no_slack,
            max_surfaces=args.max_surfaces,
            no_enrich=args.no_enrich,
        )
    elif args.cmd == "op-vet":
        cmd_op_vet(args.username)
    elif args.cmd == "discover":
        cmd_discover(args.answers_json, args.homepage, args.vertical,
                     args.competitors, args.fresh_window_hours)
    elif args.cmd == "status":
        cmd_status()
    elif args.cmd == "blog" and args.blogcmd == "ingest":
        cmd_blog_ingest()


_MAX_SURFACES_BANNER_SHOWN = False


def _emit_max_surfaces_warning(n: int) -> None:
    """One-time stderr banner when --max-surfaces > 12. Cheap process-local
    flag (not persisted) — re-running re-prints, which is fine: the user
    explicitly opted in via the flag every time."""
    global _MAX_SURFACES_BANNER_SHOWN
    if _MAX_SURFACES_BANNER_SHOWN:
        return
    _MAX_SURFACES_BANNER_SHOWN = True
    sys.stderr.write(
        f"[cli] --max-surfaces={n}. Reddit's API is fine with this volume "
        f"(roughly 30 read req/day, well under 100 QPM). The risk is YOUR "
        f"review fatigue. Default cap of 12 exists because attention drops "
        f"80% past position 10 (Nielsen Norman). Plan ~1 min per surface.\n"
    )
    sys.stderr.flush()


def cmd_discover(answers_json: str, homepage: str, vertical: str | None,
                 competitors_csv: str = "", fresh_window_hours: int | None = None) -> None:
    """Live subreddit discovery for the /subscope-onboard T5 card.

    Reads JSON answers from --answers-json. Two forms accepted:
      (a) literal JSON string: --answers-json '{"what_offering": ...}'
      (b) the literal token '-' or '/dev/stdin' to read from stdin instead.
          This avoids shell-quote breakage when user input contains apostrophes
          (e.g. T4 = "we're tired of saas pricing"). The skill orchestrator
          should prefer stdin for any user-derived input.

    Writes ranked sub list + clarifier signals as JSON to stdout.
    """
    if answers_json in ("-", "/dev/stdin"):
        answers_json = sys.stdin.read()
    try:
        answers = json.loads(answers_json)
        if not isinstance(answers, dict):
            raise ValueError("answers must be a JSON object")
    except (json.JSONDecodeError, ValueError) as e:
        print(json.dumps({"error": f"invalid --answers-json: {e}"}))
        sys.exit(2)

    # Comma-separated competitors from skill (independent of DFS cache).
    # Strip + dedup; empty strings filtered out.
    extra_competitors = [c.strip() for c in (competitors_csv or "").split(",")
                         if c.strip()]

    kwargs = {"vertical": vertical, "extra_competitors": extra_competitors or None}
    if fresh_window_hours is not None:
        kwargs["fresh_window_hours"] = fresh_window_hours

    with store.connect() as conn:
        result = discover.discover_subs_for_profile(
            answers, homepage or "", conn, **kwargs,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_op_vet(username: str) -> None:
    """Standalone OP profile scorer. Outputs JSON: {karma, age_days,
    sub_breakdown_top, verdict, reason}. Used by `/subscope-op-vet`.

    Honors weights.yml `author_vet:` block so /tune-loosened thresholds apply
    to ad-hoc op-vets too (architect's consistency note from PIPE-1 review).
    """
    weights = _load_configs(mode="default")["weights"]
    with store.connect() as conn:
        result = author_vet.vet_author(username, conn=conn, weights=weights)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
