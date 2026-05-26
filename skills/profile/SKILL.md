---
name: profile
description: Per-section deep dive for refining an existing subscope targeting profile. Not a full re-interview, just the section that's drifted. Pick one section (competitors, pain language, subreddit tiers, keywords, buyer titles, customers, content map, positioning), answer 1-3 focused questions, and the relevant YAML file is rewritten in place. Other sections are untouched. Use this after a few scans when one dimension feels off (too much noise from one sub, competitor anchor missing a name, pain phrasing not landing). Triggers on "profile", "/subscope:profile", "refine my profile", "redo competitor anchor", "redo subreddits", "rebuild pain language", "swap a subreddit", "update my targeting", "fix my profile", "tighten my profile".
allowed-tools: Bash, Read, Write, Edit, WebFetch
---

# /subscope:profile

Per-section deep dive. Not a full re-interview, just the section that's drifted.

You ran `/subscope:onboard` once and the four config files at `~/.config/subscope/` are in place. After a few scans you notice: one subreddit floods the results with noise, the competitor anchor is missing a name, the pain language doesn't match how your buyers actually talk. That's the job for this skill. Pick the section, answer 1-3 focused questions, and only that section is rewritten.

If you've never run onboarding before, run `/subscope:onboard` first. This skill assumes an existing config.

## Procedure

### Step 1: Verify an onboarded config exists

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -c "
from pathlib import Path
from subscope.lib import store
cfg = store.xdg_config_dir()
required = ['subreddits.yml', 'keywords.yml', 'brand-anchor.yml', 'example-pains.yml']
missing = [f for f in required if not (cfg / f).exists()]
if missing:
    print('MISSING:', missing)
    print('Run /subscope:onboard first.')
else:
    print('OK')
"
```

If any required file is missing, stop and direct the user to `/subscope:onboard`.

### Step 2: Pick a section

Print verbatim:

```
Which section needs a refresh?

  [1] Competitor anchor      brand-anchor.yml
  [2] Pain language          example-pains.yml
  [3] Subreddit tiers        subreddits.yml
  [4] Keywords               keywords.yml
  [5] Buyer titles           subreddits.yml (operator/builder mapping)
  [6] Customers              regenerate inferred customer list
  [7] Content map            blog-map.yml (your own URLs)
  [8] Positioning            regenerate the one-line positioning, may cascade

Type a number.
```

If user types a number not in 1-8, re-prompt once. Multiple sections in one run are allowed, ask for a comma-separated list. Each section then runs in sequence, sharing the same review-and-write pattern.

### Step 3: Run the chosen section flow

Each section follows the same shape: show the current value, ask 1-3 focused questions, propose the new value, write on `confirm`.

#### Section 1: Competitor anchor (brand-anchor.yml)

Show current:

```bash
cat ~/.config/subscope/brand-anchor.yml
```

Ask:

```
Current anchor has <N> competitors. What needs to change?

  [a] Add a competitor I'm missing
  [b] Drop a competitor that doesn't fit anymore
  [c] Reorder (move the top 3 churn-from brands to the top)
  [d] Full rebuild (paste 5-10 tools your buyer evaluates you against)

Pick one or paste edits directly (e.g. "add Apollo and Clay, drop Outreach").
```

Apply edits in-memory to the full payload (loaded from `~/.config/subscope/`), then validate the whole payload via the existing helper. See [Step 4](#step-4--load-mutate-validate-write-the-full-payload) below for the shared shell pattern. Show the diff (old vs new) and ask: `confirm / show full file / edit again`. Write on `confirm`.

#### Section 2: Pain language (example-pains.yml)

Show current top 5 pain phrases.

Ask:

```
Pain language is load-bearing. The classifier looks for these phrases in
post titles and bodies.

  [a] Add a phrase your buyer actually says (verbatim, from Slack/calls/reviews)
  [b] Drop a phrase that produced noise
  [c] Paste 3-5 verbatim quotes and I'll extract phrases

Generic SEO-style keywords don't work here. "buyer intent platform" is yours;
"this is killing me, we're paying for 4 tools that do the same thing" is theirs.
```

Process. Validate. Diff. Confirm. Write.

#### Section 3: Subreddit tiers (subreddits.yml)

Show current Tier 1 (daily) and Tier 2 (opportunistic) splits.

Ask:

```
Which subs feel off?

  [a] Move a sub between tiers (Tier 1 ↔ Tier 2)
  [b] Drop a sub that floods with noise
  [c] Add a sub I should be watching
  [d] Quarantine a sub (keep in config but skip on every scan)

Paste edits like "move r/SaaS to tier 1, drop r/marketing, add r/RevOps".
```

For each `add` candidate, optionally validate via warm-scan:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m subscope.cli fetch-score \
  --subs <NEW_SUB> --limit-per-sub 10 --daily-cap 5 --no-slack --max-surfaces 5 \
  2>/dev/null || echo "warm-scan-skipped"
```

Diff. Confirm. Write.

#### Section 4: Keywords (keywords.yml)

Show current Shared / Operator / Builder buckets.

Ask:

```
Which bucket needs a refresh?

  [a] Shared (cross-cutting phrases your buyer uses regardless of role)
  [b] Operator (work-pain phrases, "this is broken", "we need to ditch X")
  [c] Builder (technical/replacement phrases, "alternative to", "open source")

Paste add/drop edits for that bucket.
```

Process. Validate (each bucket has min/max caps in config/weights.yml). Diff. Confirm. Write.

#### Section 5: Buyer titles (subreddits.yml, operator/builder mapping)

The buyer-title list drives which keyword bucket a post matches against.

Ask:

```
What job titles does your buyer use today? Examples:
  Operator side: Head of Ops, RevOps Lead, COO, Founder
  Builder side: indie hacker, fractional CTO, technical founder, engineer

Paste 2-4 titles per side, or just paste the side that's off.
```

Process. The title strings update the operator/builder routing in subreddits.yml. Diff. Confirm. Write.

#### Section 6: Customers (regenerate inferred customer list)

The customer list isn't a YAML file, it's metadata used during synthesis to validate the other sections. Refreshing it produces sharper edits in future profile runs.

Ask:

```
Describe your last 3 customers (or the most recent if names matter).
Job title, company size, what tool/process they replaced to buy you.

The "what they replaced" clause is the gold. It reveals adjacent tool
categories and the trigger event.
```

Free-text. Save to `~/.config/subscope/.customers.json` as a reference. No YAML write, but the next time you run `/subscope:profile` on competitors or pain language, this list is the seed.

#### Section 7: Content map (blog-map.yml)

Show current entries.

Ask:

```
Paste 3-5 URLs of your own content (blog, YouTube, threads) you'd reference
in a Reddit reply. WebFetch extracts titles and H1s.

Type "drop URL <url>" to remove an entry.
Type "clear" to wipe the map.
```

Process. WebFetch each new URL. Diff. Confirm. Write.

#### Section 8: Positioning (cascading rebuild)

WARNING: positioning is upstream of everything else. Rebuilding it may surface contradictions in the other sections.

Show current positioning string from the metadata.

Ask:

```
Rewrite the one-sentence positioning. Offer + buyer in a noun-verb-payer triple.

After the rewrite, the system flags any other section that now looks
inconsistent (e.g. competitors targeting a different ICP than the new
positioning). You decide whether to cascade or stop.
```

After positioning is updated, you (Claude) manually inspect the other sections in the payload for obvious contradictions (e.g. competitor anchor targeting an ICP the new positioning excludes). Surface flagged sections in one list. For each flagged section, offer the user a `cascade / keep` choice. Run the relevant section flow above for each `cascade`.

### Step 4: Load, mutate, validate, write the full payload

Section edits happen in-memory against the full payload. The engine writes all four files atomically each time, with backup. The validator catches cross-section breakage.

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 << 'PY'
import json, yaml
from pathlib import Path
from subscope.lib import profile_synth, store

# 1. Load current config into a payload-shaped dict
cfg_dir = store.xdg_config_dir()
payload = {
    'subreddits': yaml.safe_load((cfg_dir / 'subreddits.yml').read_text()),
    'keywords':   yaml.safe_load((cfg_dir / 'keywords.yml').read_text()),
    'brand_anchor': yaml.safe_load((cfg_dir / 'brand-anchor.yml').read_text()),
    'example_pains': yaml.safe_load((cfg_dir / 'example-pains.yml').read_text()),
}

# 2. Apply the section edit
#    Claude substitutes the section-specific mutation here, e.g.
#    payload['brand_anchor']['competitors'] = $NEW_COMPETITORS
$SECTION_MUTATION

# 3. Validate the full payload
weights_path = Path("config/weights.yml")
weights_cfg = yaml.safe_load(weights_path.read_text()) if weights_path.exists() else {}
ok, problems = profile_synth.validate_synthesis(payload, weights_cfg)
if not ok:
    print("VALIDATION FAILED:")
    for p in problems:
        print(f"  - {p}")
    raise SystemExit(1)

# 4. Write all four files atomically with backup
files = profile_synth.to_yaml_files(payload)
written = profile_synth.write_to_xdg(files, backup=True)
for name, path in written.items():
    print(f"  wrote: {path}")
PY
```

Backups land alongside the existing files via `write_to_xdg(..., backup=True)`. Only the targeted section's YAML contents differ from the previous write; the validator ensures the unchanged sections still satisfy schema after the edit.

### Step 5: Next-action footer

After all chosen sections are written:

```
Updated: <list of sections>
Backed up: <list of backup paths>

Run /subscope:run to see the change reflected in the next scan.
Run /subscope:tune after 2-3 scans if the ranker needs another pass.
```

## Anti-patterns

- **Never run the full 8-question onboard flow inside /profile.** That's `/subscope:onboard`. This skill is per-section only.
- **Never write multiple sections without separate confirms.** Each section is its own write gate.
- **Never bypass the validator.** Each section has a min/max constraint set in `config/weights.yml`. Pasting "add 40 competitors" fails validation, surface the error inline.
- **No exclamation marks. No em dashes.** Operational tone.
- **Don't propose section 8 (positioning) casually.** It cascades. Only run it when the user explicitly asks to rebuild positioning, not as a "while we're here" suggestion.
- **Don't prompt the user with a blank field.** Always show the current value first.

## Resumability

Per-section runs are short enough that resumability isn't needed. If the user abandons mid-section, nothing is written and the next invocation starts fresh.

## When to use this vs /subscope:onboard

| Situation | Skill |
|---|---|
| First install, no config yet | `/subscope:onboard` |
| Re-ran from a fresh clone, want to redo everything | `/subscope:onboard` (delete config first) |
| One section feels off (competitor anchor stale, pain language too generic) | `/subscope:profile` |
| Multiple sections feel off but core targeting is right | `/subscope:profile` (run the relevant sections in sequence) |
| Pivoting to a new ICP entirely | `/subscope:onboard` (positioning has fully changed) |

If in doubt: profile for refinement, onboard for re-orientation.
