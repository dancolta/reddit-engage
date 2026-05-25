"""Inline-chat markdown renderer for the daily list.

Format matches plan Section 4e: grouped by tier, tagged with saturation,
score visible, blog match cited (no full draft suggestion).
"""
from __future__ import annotations

import time
from typing import Any


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
    summary = f"{len(surfaces)} surfaces today ({len(t1)} Tier 1 / {len(t2)} Tier 2)."
    if dropped_counts:
        parts = [f"{v} {k}" for k, v in dropped_counts.items() if v]
        if parts:
            summary += " Dropped at gate: " + ", ".join(parts) + "."
    lines.append(summary)
    if run_notes:
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


def render_json_payload(surfaces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact representation for the orchestrator to push to Notion."""
    out: list[dict[str, Any]] = []
    for s in surfaces:
        post = s["post"]
        sub = s["sub"]
        out.append({
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
            "blog_matches": [
                {"title": m["title"], "url": m["url"]}
                for m in s.get("blog_matches", [])
            ],
        })
    return out
