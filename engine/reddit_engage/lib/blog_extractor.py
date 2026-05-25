"""Rule-based keyword extractor for new blog posts.

Triggered by SKILL.md orchestrator when Playwright detects a new blog URL.
The orchestrator passes title + body text via stdin; we extract signature
keywords deterministically. No LLM call by default; orchestrator can fall
back to a Claude prompt only if we return fewer than 3 keywords.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from typing import Any


SAAS_BRANDS = {
    "Apollo", "Apollo.io", "Bill.com", "BILL.com", "HubSpot", "Calendly",
    "Zapier", "Make", "Make.com", "Mailchimp", "Greenhouse", "Lever",
    "Intercom", "Zendesk", "Gainsight", "Pipedrive", "Mixpanel", "PostHog",
    "Hootsuite", "Buffer", "Phantombuster", "Apify", "Lemlist", "Instantly",
    "ZoomInfo", "Outreach.io", "Salesforce", "Notion", "Airtable", "Typeform",
    "Docusign", "Retool", "Tooljet", "Appsmith", "Bubble", "Webflow",
    "Dext", "Hubdoc", "Xero", "QuickBooks", "Ramp", "Brex", "Stripe",
    "Slack", "Linear", "Asana", "Monday", "Loom", "Cal.com", "Datadog",
    "Plausible", "Listmonk", "Chatwoot", "EspoCRM", "Mautic", "Twenty",
    "Documenso", "Formbricks", "Tally", "Cap.so", "OpenSign", "Akaunting",
    "Invoice Ninja",
}

STACK_TERMS = {
    "Hetzner", "docker-compose", "Render", "Railway", "Fly.io", "Neon",
    "Supabase", "Postgres", "Postmark", "OpenAI", "Anthropic", "Claude",
    "GPT-4o-mini", "Gemini", "Hunter", "Proxycurl", "Slack Bolt",
    "Vercel Functions", "Next.js", "SQLite", "FastAPI",
}

SIGNATURE_PHRASES = {
    "build vs buy", "replace your SaaS", "cost math", "break-even",
    "stack costs", "vendor moat", "feature overlap", "SaaS sprawl",
    "deliverability", "AP automation", "invoice approval", "Slack-native",
    "fifth-tab problem", "seat math", "self-host", "self-hosted",
    "open-source alternative", "outreach stack", "cold email reply rate",
    "audit trail", "build it yourself",
}


def _extract_matches(text: str, vocabulary: set[str]) -> list[str]:
    found: list[str] = []
    haystack = text
    for term in vocabulary:
        if term.lower() in haystack.lower():
            found.append(term)
    return found


def extract_keywords(title: str, body: str, top_n: int = 8) -> list[str]:
    """Return up to top_n signature keywords from a blog post."""
    full = f"{title}\n{body}"

    keywords: list[str] = []
    keywords.extend(_extract_matches(full, SIGNATURE_PHRASES))
    keywords.extend(_extract_matches(full, SAAS_BRANDS))
    keywords.extend(_extract_matches(full, STACK_TERMS))

    # Deduplicate while preserving order, cap to top_n
    seen = set()
    unique: list[str] = []
    for k in keywords:
        if k.lower() not in seen:
            seen.add(k.lower())
            unique.append(k)
        if len(unique) >= top_n:
            break
    return unique


def infer_pain(title: str, body: str) -> str:
    """Heuristic 1-line pain summary. Pull the first sentence that contains
    a SaaS name + a dollar figure, fall back to title."""
    sentences = re.split(r"(?<=[.!?])\s+", body[:2000])
    for s in sentences:
        if re.search(r"\$\d", s) and any(brand.lower() in s.lower() for brand in SAAS_BRANDS):
            return s.strip()[:220]
    return title


def infer_persona(title: str, body: str) -> str:
    """Heuristic persona detection from common role markers."""
    full = f"{title}\n{body[:3000]}".lower()
    if "cfo" in full or "finance team" in full or "accounting" in full:
        return "SME finance team"
    if "sdr" in full or "sales ops" in full or "outbound" in full or "outreach" in full:
        return "Sales ops, outbound lead"
    if "founder" in full or "sme" in full or "small business" in full:
        return "SME founder, ops lead"
    if "indie" in full or "solo builder" in full:
        return "Indie hacker, solo builder"
    return "SME operator"


def infer_saas_replaced(title: str, body: str) -> str:
    """Comma-list of SaaS brands mentioned in title + body."""
    full = f"{title}\n{body}"
    found = _extract_matches(full, SAAS_BRANDS)
    seen = set()
    unique: list[str] = []
    for s in found:
        if s.lower() not in seen:
            seen.add(s.lower())
            unique.append(s)
    return ", ".join(unique[:6])


def infer_stack(title: str, body: str) -> str:
    full = f"{title}\n{body}"
    found = _extract_matches(full, STACK_TERMS)
    seen = set()
    unique: list[str] = []
    for s in found:
        if s.lower() not in seen:
            seen.add(s.lower())
            unique.append(s)
    return ", ".join(unique[:8])


def build_blog_post(url: str, title: str, body: str) -> dict[str, Any]:
    """Build a complete blog_posts row from raw scraped content."""
    return {
        "url": url,
        "title": title,
        "pain": infer_pain(title, body),
        "saas_replaced": infer_saas_replaced(title, body) or "various SaaS",
        "persona": infer_persona(title, body),
        "stack": infer_stack(title, body) or "Python, Hetzner, Postgres",
        "keywords": extract_keywords(title, body),
    }


def main() -> None:
    """CLI entry point: stdin = {"url": ..., "title": ..., "body": ...}, stdout = blog_post JSON."""
    payload = json.load(sys.stdin)
    blog = build_blog_post(payload["url"], payload["title"], payload["body"])
    json.dump(blog, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
