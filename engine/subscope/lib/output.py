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
}

GROUP_ORDER = ("Subreddit rules", "Author quality", "Content rules")


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
    nonzero = {k: v for k, v in dropped_counts.items() if v}
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


def render(surfaces: list[dict[str, Any]], run_notes: str = "",
           dropped_counts: dict[str, int] | None = None) -> str:
    """Render the daily list. surfaces is the orchestrator's ranked output."""
    if not surfaces:
        return "No qualifying posts today. Empty days are fine.\n" + (run_notes and f"\nStatus: {run_notes}\n" or "")

    t1 = [s for s in surfaces if s["sub"]["tier"] == 1]
    t2 = [s for s in surfaces if s["sub"]["tier"] == 2]

    lines: list[str] = []
    if t1:
        lines.append(f"🟢 TIER 1, daily-scan ({len(t1)} surfaces)\n")
        for i, s in enumerate(t1, start=1):
            lines.append(_render_item(i, s))
            lines.append("")
    if t2:
        lines.append(f"🟡 TIER 2, opportunistic ({len(t2)} surfaces)\n")
        offset = len(t1)
        for i, s in enumerate(t2, start=offset + 1):
            lines.append(_render_item(i, s))
            lines.append("")

    lines.append("──")
    lines.append(f"{len(surfaces)} surfaces today ({len(t1)} Tier 1, {len(t2)} Tier 2).")
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


def render_table(surfaces: list[dict[str, Any]],
                 dropped_counts: dict[str, int] | None = None) -> str:
    """Render the daily list as a compact Markdown table.

    Used as the default surface when ~/.config/subscope/surface.yml says so
    (or no surface.yml exists). Renders cleanly inside Claude Code chat;
    user clicks the URL column directly to open the thread.

    Columns: # | Tier | Sub | Title (truncated) | ↑ | OP score | Open
    """
    if not surfaces:
        return "No qualifying posts today. Empty days are fine."

    t1 = [s for s in surfaces if s["sub"]["tier"] == 1]
    t2 = [s for s in surfaces if s["sub"]["tier"] == 2]
    lines: list[str] = []
    header = "| # | Tier | Sub | Title | ↑ | OP score | Open |\n|---|---|---|---|---|---|---|"

    if t1:
        lines.append(f"### TIER 1, daily-scan ({len(t1)})")
        lines.append("")
        lines.append(header)
        for i, s in enumerate(t1, start=1):
            lines.append(_render_table_row(i, s))
        lines.append("")
    if t2:
        lines.append(f"### TIER 2, opportunistic ({len(t2)})")
        lines.append("")
        lines.append(header)
        offset = len(t1)
        for i, s in enumerate(t2, start=offset + 1):
            lines.append(_render_table_row(i, s))
        lines.append("")

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


def render_json_payload(surfaces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact representation for the orchestrator to push to Notion."""
    out: list[dict[str, Any]] = []
    for s in surfaces:
        post = s["post"]
        sub = s["sub"]
        entry = {
            "post_id": post["id"],
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
    """One-line operator score for Notion 'OP score' column.

    Example: '2y old · 4.2k karma · 12% wrong-audience'.

    Empty string when vet data missing (e.g. cache miss + fetch failure).
    Saves the user a profile-open click before deciding to reply.
    """
    if not vet:
        return ""
    age_days = vet.get("account_age_days") or 0
    if age_days >= 365:
        age = f"{age_days // 365}y"
    elif age_days >= 30:
        age = f"{age_days // 30}mo"
    else:
        age = f"{age_days}d"
    karma = vet.get("comment_karma") or 0
    if karma >= 1000:
        k = f"{karma / 1000:.1f}k"
    else:
        k = str(karma)
    frac = vet.get("wrong_audience_fraction")
    if frac is None:
        return f"{age} old · {k} karma"
    return f"{age} old · {k} karma · {int(frac * 100)}% wrong-audience"
