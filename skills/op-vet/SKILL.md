---
name: op-vet
description: Score a Reddit user's profile before replying. Returns karma, account age, sub-activity breakdown, and a GO / HOLD / SKIP verdict. Useful when you spot a thread that looks promising but want to confirm OP is a real operator (not a throwaway, karma farmer, or hustle-bro). Triggers on "op vet", "/subseek:op-vet <username>", "vet this user", "is u/<name> legit", "check OP profile", "profile vet".
allowed-tools: Bash, Read
---

# /subseek:op-vet (utility, one-shot)

Score a single Reddit user's profile. Used BEFORE drafting a reply when you want to confirm OP is a real operator.

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m subseek.cli op-vet "$USERNAME"
```

Engine returns JSON:

```json
{
  "verdict": "pass" | "fail",
  "reason": null | "account_too_young" | "low_karma" | "wrong_audience" | "deleted_or_private" | "fetch_failed",
  "comment_karma": 542,
  "account_age_days": 730,
  "wrong_audience_fraction": 0.12,
  "from_cache": false
}
```

Translate to a human-readable verdict in chat:

| Verdict | reason | Show |
|---|---|---|
| pass | (none) | **GO** — real operator profile |
| pass | fetch_failed | **HOLD** — couldn't read profile, decide manually |
| fail | account_too_young | **SKIP** — account <30d old |
| fail | low_karma | **SKIP** — comment karma < 50 |
| fail | wrong_audience | **SKIP** — >80% in hustle-bro subs |
| fail | deleted_or_private | **SKIP** — account gone or shadowbanned |

The 7-day SQLite cache means repeat lookups of the same OP are free. No need to vet manually — the daily run already vets every OP it surfaces (per Phase 1.5).
