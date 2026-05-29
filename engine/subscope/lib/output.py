"""Inline-chat markdown renderer for the daily list.

Format matches plan Section 4e: grouped by tier, tagged with saturation,
score visible, blog match cited (no full draft suggestion).
"""
from __future__ import annotations

import time
from typing import Any


# Engine counter key → (group, user-friendly label)
# Used by render_footer() to translate dropped_counts dict into plain English.
# Order inside each group reflects logical reading order, but rendering sorts
# by count descending within each group.
DROPPED_LABELS: dict[str, tuple[str, str]] = {
    # Subreddit rules
    "tier1_post_age": ("Subreddit rules", "post too old (Tier 1)"),
    "tier2_post_age": ("Subreddit rules", "post too old (Tier 2)"),
    "tier1_keyword_density": ("Subreddit rules", "weak keyword match (Tier 1)"),
    "tier2_keyword_density": ("Subreddit rules", "weak keyword match (Tier 2)"),
    "tier1_no_saas_brand": ("Subreddit rules", "no SaaS brand mentioned (Tier 1)"),
    "tier2_no_saas_brand": ("Subreddit rules", "no SaaS brand mentioned (Tier 2)"),
    "tier3_quarantined": ("Subreddit rules", "quarantined sub (Tier 3, off by config)"),
    "tier1_velocity_floor": ("Subreddit rules", "thread engagement too low (Tier 1)"),
    "tier2_velocity_floor": ("Subreddit rules", "thread engagement too low (Tier 2)"),
    # Author quality
    "author_vet_low_karma": ("Author quality", "OP karma too low"),
    "author_vet_account_too_young": ("Author quality", "OP account too young"),
    "author_vet_throwaway": ("Author quality", "OP looks like a throwaway"),
    "author_vet_wrong_audience": ("Author quality", "OP posts mostly in unrelated subs"),
    # Content rules
    "vendor_content": ("Content rules", "vendor / promo content"),
    "negative_topic": ("Content rules", "negative-topic blocklist"),
    "classifier_vendor": ("Content rules", "LLM flagged as vendor pitch"),
    # Authority track (dual-track second pass over the soft-reject pool)
    "authority_absolute_reject": ("Authority track", "failed an absolute reject"),
    "authority_not_eligible_reason": ("Authority track", "not an on-topic near-miss"),
    "authority_no_question": ("Authority track", "no question to answer"),
    "authority_keyword_density": ("Authority track", "weak topical fit"),
    "authority_career_identity": ("Authority track", "career / identity question"),
    "authority_author_vet": ("Authority track", "OP did not pass vetting"),
}

GROUP_ORDER = ("Subreddit rules", "Author quality", "Content rules", "Authority track")


def _humanize_unknown_key(key: str) -> str:
    """Fallback for counter keys not in DROPPED_LABELS. Underscores to spaces."""
    return key.replace("_", " ")


def _build_dropped_footer(dropped_counts: dict[str, int]) -> list[str]:
    """Render the grouped dropped-counts footer as a list of lines.

    Returns an empty list when there's nothing to show. The caller decides
    how to integrate (markdown vs table renderers both consume this).

    Layout:
        <total> posts filtered before scoring:

        Group A
          NN  label
          NN  label

        Group B
          NN  label
    """
    # `fetch_blocked` / `fetch_rate_limited` are run-status markers, not
    # pre-scoring drops. They are surfaced via the JSON `status` field and the
    # no-surface copy, so keep them out of the "filtered before scoring" footer.
    _status_markers = {"fetch_blocked", "fetch_rate_limited"}
    nonzero = {k: v for k, v in dropped_counts.items() if v and k not in _status_markers}
    if not nonzero:
        return []
    total = sum(nonzero.values())

    # Bucket by group
    grouped: dict[str, list[tuple[int, str]]] = {g: [] for g in GROUP_ORDER}
    unknown_group: list[tuple[int, str]] = []
    for key, count in nonzero.items():
        if key in DROPPED_LABELS:
            group, label = DROPPED_LABELS[key]
            grouped.setdefault(group, []).append((count, label))
        else:
            unknown_group.append((count, _humanize_unknown_key(key)))

    lines: list[str] = [f"{total} posts filtered before scoring:"]
    for group in GROUP_ORDER:
        rows = grouped.get(group, [])
        if not rows:
            continue
        rows.sort(key=lambda r: -r[0])  # descending count
        lines.append("")
        lines.append(group)
        for count, label in rows:
            lines.append(f"  {count:>3}  {label}")
    if unknown_group:
        unknown_group.sort(key=lambda r: -r[0])
        lines.append("")
        lines.append("Other")
        for count, label in unknown_group:
            lines.append(f"  {count:>3}  {label}")
    return lines


def _age_label(created_utc: int, now: int | None = None) -> str:
    t = now if now is not None else int(time.time())
    delta_min = max(0, (t - int(created_utc)) // 60)
    if delta_min < 60:
        return f"{delta_min}m ago"
    if delta_min < 24 * 60:
        return f"{delta_min // 60}h ago"
    return f"{delta_min // (24 * 60)}d ago"


# Dual-track section headers. Buyer FIRST. No em dashes.
BUYER_HEADER = "BUYER SIGNALS ({n})  someone is shopping, a reply moves a deal"
AUTHORITY_HEADER = "AUTHORITY PLAYS ({n})  answer to build presence, no buyer yet"


def _render_buyer_body(surfaces: list[dict[str, Any]], start_index: int = 0) -> list[str]:
    """Render the tier-split buyer body (the historical render layout).

    Returns the list of lines (tier headers + items). `start_index` offsets the
    per-item numbering so a leading section header does not reset the count.
    """
    t1 = [s for s in surfaces if s["sub"]["tier"] == 1]
    t2 = [s for s in surfaces if s["sub"]["tier"] == 2]
    lines: list[str] = []
    if t1:
        lines.append(f"🟢 TIER 1, daily-scan ({len(t1)} surfaces)\n")
        for i, s in enumerate(t1, start=start_index + 1):
            lines.append(_render_item(i, s))
            lines.append("")
    if t2:
        lines.append(f"🟡 TIER 2, opportunistic ({len(t2)} surfaces)\n")
        offset = start_index + len(t1)
        for i, s in enumerate(t2, start=offset + 1):
            lines.append(_render_item(i, s))
            lines.append("")
    return lines


def render(surfaces: list[dict[str, Any]], run_notes: str = "",
           dropped_counts: dict[str, int] | None = None,
           authority_surfaces: list[dict[str, Any]] | None = None) -> str:
    """Render the daily list. surfaces is the orchestrator's ranked buyer output.

    Dual-track: when `authority_surfaces` is non-empty, the output gains two
    labeled sections (buyer FIRST), each with a header line. When it is empty,
    the output is the historical buyer-only layout byte-for-byte (so disabling
    the authority track reverts to today's exact behavior). An empty authority
    track never prints an authority header.
    """
    authority_surfaces = authority_surfaces or []

    if not surfaces and not authority_surfaces:
        return "No qualifying posts today. Empty days are fine.\n" + (run_notes and f"\nStatus: {run_notes}\n" or "")

    t1 = [s for s in surfaces if s["sub"]["tier"] == 1]
    t2 = [s for s in surfaces if s["sub"]["tier"] == 2]

    lines: list[str] = []
    if authority_surfaces:
        # Two-section mode: label the buyer block, then the authority block.
        lines.append(BUYER_HEADER.format(n=len(surfaces)))
        lines.append("")
        lines.extend(_render_buyer_body(surfaces))
        lines.append(AUTHORITY_HEADER.format(n=len(authority_surfaces)))
        lines.append("")
        for i, s in enumerate(authority_surfaces, start=len(surfaces) + 1):
            lines.append(_render_item(i, s))
            lines.append("")
    else:
        # Historical buyer-only layout (unchanged).
        lines.extend(_render_buyer_body(surfaces))

    lines.append("──")
    total = len(surfaces) + len(authority_surfaces)
    summary = f"{len(surfaces)} surfaces today ({len(t1)} Tier 1, {len(t2)} Tier 2)."
    if authority_surfaces:
        summary = (f"{total} surfaces today: {len(surfaces)} buyer "
                   f"({len(t1)} Tier 1, {len(t2)} Tier 2), "
                   f"{len(authority_surfaces)} authority.")
    lines.append(summary)
    if dropped_counts:
        footer = _build_dropped_footer(dropped_counts)
        if footer:
            lines.append("")
            lines.extend(footer)
    if run_notes:
        lines.append("")
        lines.append(f"Status: {run_notes}")
    return "\n".join(lines)


def _render_item(index: int, s: dict[str, Any]) -> str:
    post = s["post"]
    sub = s["sub"]
    tier = sub["tier"]
    sat = sub.get("saturation")
    tier_tag = f"T{tier}" + (f" {sat}" if (tier == 2 and sat) else "")

    blog_lines = ""
    if s.get("blog_matches"):
        blogs = "\n".join(
            f"       → {m['title']}\n         {m['url']}"
            for m in s["blog_matches"][:2]
        )
        blog_lines = f"\nBlog:  {blogs.lstrip()}"

    age = _age_label(post["created_utc"])
    return (
        f"#{index}   [{tier_tag}] r/{post['subreddit']}   {age}   "
        f"↑ {post['score']}   💬 {post['num_comments']}   score {s.get('score_internal', 0):.1f}\n"
        f"Title: \"{post['title']}\"\n"
        f"URL:   {post['url']}\n"
        f"Pain:  {s.get('pain_summary', _truncate(post.get('body', ''), 120))}\n"
        f"Fit:   {s.get('fit_summary', _default_fit(sub, s.get('blog_matches', [])))}"
        f"{blog_lines}"
    )


def _truncate(text: str, n: int) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text[:n] + ("..." if len(text) > n else "")


def _default_fit(sub: dict[str, Any], blog_matches: list[dict[str, Any]]) -> str:
    if blog_matches:
        return f"Backed by {blog_matches[0]['title']}. Tone-fit for r/{sub['name']}."
    return f"Topic-adjacent fit for r/{sub['name']}. No direct blog backing yet."


_TABLE_HEADER = "| # | Tier | Sub | Title | ↑ | OP score | Open |\n|---|---|---|---|---|---|---|"


def _render_buyer_table_body(surfaces: list[dict[str, Any]], start_index: int = 0) -> list[str]:
    """Render the tier-split buyer table body (historical layout)."""
    t1 = [s for s in surfaces if s["sub"]["tier"] == 1]
    t2 = [s for s in surfaces if s["sub"]["tier"] == 2]
    lines: list[str] = []
    if t1:
        lines.append(f"### TIER 1, daily-scan ({len(t1)})")
        lines.append("")
        lines.append(_TABLE_HEADER)
        for i, s in enumerate(t1, start=start_index + 1):
            lines.append(_render_table_row(i, s))
        lines.append("")
    if t2:
        lines.append(f"### TIER 2, opportunistic ({len(t2)})")
        lines.append("")
        lines.append(_TABLE_HEADER)
        offset = start_index + len(t1)
        for i, s in enumerate(t2, start=offset + 1):
            lines.append(_render_table_row(i, s))
        lines.append("")
    return lines


def render_table(surfaces: list[dict[str, Any]],
                 dropped_counts: dict[str, int] | None = None,
                 authority_surfaces: list[dict[str, Any]] | None = None) -> str:
    """Render the daily list as a compact Markdown table.

    Used as the default surface when ~/.config/subscope/surface.yml says so
    (or no surface.yml exists). Renders cleanly inside Claude Code chat;
    user clicks the URL column directly to open the thread.

    Columns: # | Tier | Sub | Title (truncated) | ↑ | OP score | Open

    Dual-track: when `authority_surfaces` is non-empty, a labeled "BUYER SIGNALS"
    block (with its tier sub-tables) comes FIRST, then an "AUTHORITY PLAYS" block.
    When it is empty, the layout is the historical buyer-only table byte-for-byte
    (so disabling the authority track reverts to today's exact behavior). An empty
    authority track never prints an authority header.
    """
    authority_surfaces = authority_surfaces or []

    if not surfaces and not authority_surfaces:
        return "No qualifying posts today. Empty days are fine."

    t1 = [s for s in surfaces if s["sub"]["tier"] == 1]
    t2 = [s for s in surfaces if s["sub"]["tier"] == 2]
    lines: list[str] = []

    if authority_surfaces:
        lines.append(f"## {BUYER_HEADER.format(n=len(surfaces))}")
        lines.append("")
        lines.extend(_render_buyer_table_body(surfaces))
        lines.append(f"## {AUTHORITY_HEADER.format(n=len(authority_surfaces))}")
        lines.append("")
        lines.append(_TABLE_HEADER)
        for i, s in enumerate(authority_surfaces, start=len(surfaces) + 1):
            lines.append(_render_table_row(i, s))
        lines.append("")
    else:
        lines.extend(_render_buyer_table_body(surfaces))

    total = len(surfaces) + len(authority_surfaces)
    if authority_surfaces:
        lines.append(f"{total} surfaces today: {len(surfaces)} buyer "
                     f"({len(t1)} Tier 1, {len(t2)} Tier 2), "
                     f"{len(authority_surfaces)} authority.")
    else:
        lines.append(f"{len(surfaces)} surfaces today ({len(t1)} Tier 1, {len(t2)} Tier 2).")
    if dropped_counts:
        footer = _build_dropped_footer(dropped_counts)
        if footer:
            lines.append("")
            lines.extend(footer)
    return "\n".join(lines)


def _render_table_row(index: int, s: dict[str, Any]) -> str:
    """One row of the daily-scan markdown table. Markdown-safe escape on pipes."""
    post = s["post"]
    sub = s["sub"]
    tier = sub["tier"]
    sat = sub.get("saturation")
    tier_tag = f"T{tier}" + (f" {sat}" if (tier == 2 and sat) else "")
    title = (post.get("title") or "").replace("|", "\\|").replace("\n", " ")
    if len(title) > 70:
        title = title[:67] + "..."
    op = _op_score_string(s.get("vet") or {})
    # Drop the verbose labels in the table — column header already says "OP score".
    # The karma value already includes a "k" suffix when >= 1000, so we just strip
    # the word "karma" entirely, never append another k.
    op_short = (op.replace(" old · ", "/")
                  .replace(" karma · ", "/")
                  .replace(" karma", "")
                  .replace("% wrong-audience", "%wa"))
    upvotes = post.get("score", 0)
    url = post.get("url", "")
    return (f"| {index} | {tier_tag} | r/{post['subreddit']} | "
            f"{title} | {upvotes} | {op_short} | [open]({url}) |")


def render_json_payload(surfaces: list[dict[str, Any]],
                        track: str | None = None) -> list[dict[str, Any]]:
    """Compact representation for the orchestrator to push to Notion.

    `track` ("buyer" | "authority") is stamped on every entry. When None, the
    per-surface `track` field is used if present (default "buyer" for back-compat).
    """
    out: list[dict[str, Any]] = []
    for s in surfaces:
        post = s["post"]
        sub = s["sub"]
        entry = {
            "post_id": post["id"],
            "track": track or s.get("track", "buyer"),
            "tier": sub["tier"],
            "subreddit": post["subreddit"],
            "title": post["title"],
            "url": post["url"],
            "canonical_url": post["canonical_url"],
            "score_internal": s.get("score_internal", 0),
            "upvotes": post["score"],
            "comments": post["num_comments"],
            "created_utc": post["created_utc"],
            "pain_summary": s.get("pain_summary", ""),
            "fit_summary": s.get("fit_summary", ""),
            "op_score": _op_score_string(s.get("vet") or {}),
            "blog_matches": [
                {"title": m["title"], "url": m["url"]}
                for m in s.get("blog_matches", [])
            ],
        }
        # Optional enrichment block: only emitted when augment_scores attached
        # something (Firecrawl link_context, etc.). Empty dicts are omitted so
        # consumers can use `"enrichment" in surface` as the truthy check.
        enrichment = s.get("enrichment")
        if enrichment:
            entry["enrichment"] = enrichment
        out.append(entry)
    return out


def _op_score_string(vet: dict[str, Any]) -> str:
    """One-line operator score for the 'OP score' column.

    Example: '2y old · 4.2k karma · 12% wrong-audience'.

    Karma + account age come from `/user/<x>/about.json`, which returns 403 for
    anonymous requests as of 2026-05-29, so those are usually unavailable now.
    When age and karma are both absent we omit them (showing '0d old · 0 karma'
    would be a lie) and render only the wrong-audience fraction, which is still
    available via the comments RSS histogram. Empty string when nothing is known.
    """
    if not vet:
        return ""
    age_days = vet.get("account_age_days") or 0
    karma = vet.get("comment_karma") or 0
    frac = vet.get("wrong_audience_fraction")

    have_age_karma = age_days > 0 or karma > 0
    if not have_age_karma:
        # about.json unavailable: show only the audience signal we actually have.
        if frac is None:
            return ""
        return f"{int(frac * 100)}% wrong-audience"

    if age_days >= 365:
        age = f"{age_days // 365}y"
    elif age_days >= 30:
        age = f"{age_days // 30}mo"
    else:
        age = f"{age_days}d"
    if karma >= 1000:
        k = f"{karma / 1000:.1f}k"
    else:
        k = str(karma)
    if frac is None:
        return f"{age} old · {k} karma"
    return f"{age} old · {k} karma · {int(frac * 100)}% wrong-audience"
