---
name: setup
description: Interactive setup wizard for reddit-engage. Walks new users through Reddit OAuth registration, LLM provider configuration, preset selection (B2B SaaS founder / agency owner / indie hacker / consultant), optional Notion DB integration, and optional Obsidian vault wiring. Triggers on "setup reddit-engage", "/reddit-engage setup", "initialize reddit-engage", "configure reddit-engage", or when the user reports the daily run failing due to missing config.
allowed-tools: Bash, Read, Write, Edit
---

# /reddit-engage:setup

**Status:** Stub. Full implementation is Phase 7 in [PLAN.md](../../PLAN.md). For now, this skill informs the user that setup is not yet built and points them at manual config.

## Current behavior (Phase 0 stub)

Tell the user:

> The interactive setup wizard ships in Phase 7 of the build (see [PLAN.md](../../PLAN.md) §4). For now, manual setup is required:
>
> 1. **Reddit OAuth**: Register a `script`-type app at https://reddit.com/prefs/apps with redirect URI `http://localhost`. Note the 14-char client ID and the secret. Set them as plugin user config (Claude Code prompts on install) or write `~/.config/reddit-engage/oauth.json` directly with `{client_id, client_secret, username}`.
> 2. **LLM (optional, Phase 2)**: If you want intent classification, set `ANTHROPIC_API_KEY` in your shell, OR have the `claude` CLI installed and authenticated (auto-detected).
> 3. **Subs + keywords**: Copy one of `presets/*.yml` (Phase 6) into `~/.config/reddit-engage/`. Until presets ship, use `config/subreddits.yml`, `config/keywords.yml`, `config/weights.yml` as-is from the repo.
> 4. **Notion (optional)**: Drop your DB ID into `~/.config/reddit-engage/notion.yml`.
> 5. **Obsidian (optional, Phase 4)**: Drop vault path into `~/.config/reddit-engage/obsidian.yml`.
>
> Once setup ships, this skill will run all of the above as a conversational checklist with green checks.

## Future implementation pointers

Full Phase 7 spec lives across these stories (see `docs/stories/`):

- `p7.7.1-setup-skill.md` — orchestrator
- `p7.7.2-oauth-step.md` — Reddit credential walkthrough
- `p7.7.3-llm-step.md` — provider detect/prompt
- `p7.7.4-preset-step.md` — picker
- `p7.7.5-notion-step.md` — Notion DB integration
- `p7.7.6-obsidian-step.md` — vault wiring
- `p7.7.7-dry-run.md` — end-to-end validation

Do not implement those here. Phase order is intentional.
