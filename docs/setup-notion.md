# Notion daily-triage setup (optional)

`subseek` works fine without Notion — daily surfaces print inline in chat. Notion gives you a persistent board with 4 views (Hot list / Drafting queue / Pattern pulse / Replied) where you triage at your own cadence.

Total time: **3 minutes**, plug-and-play.

## 1. Create an Integration

Open https://www.notion.so/profile/integrations and click **"+ New integration"**.

| Field | Value |
|---|---|
| Name | `subseek` |
| Type | **Internal** |
| Workspace | your personal/team workspace |
| Capabilities | Read content · **Update content** · **Insert content** |

Click **Save**. On the next screen, copy the **Internal Integration Secret** (starts with `ntn_` or `secret_`). This is your `NOTION_API_KEY`.

## 2. Pick a parent page

The database needs to live somewhere in your workspace. Pick (or create) a page where you want it — could be a workspace root page like "Personal", or a sub-page like "Reddit / engage".

**Critical:** that page must be **connected** to the integration:

1. Open the page in Notion
2. Click `...` (top right) → `Connections` → `Add connections`
3. Find `subseek` and select it

Without this, the next step fails with `unauthorized`.

## 3. Get the page ID

Copy the page URL. The 32-char string at the end is the page ID:

```
https://www.notion.so/MyWorkspace/Reddit-engage-1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p
                                                  └─────────── this ───────────┘
```

Remove the dashes if any are present.

## 4. Create the DB (one command)

```bash
cd ~/Work/subseek  # or wherever the plugin engine lives
pip install -e '.[notion]'

NOTION_API_KEY=ntn_xxx python3 engine/scripts/notion_setup.py \
    --parent-page-id 1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p
```

Output:

```
✓ subseek database created
  ID:  abcdef1234567890abcdef1234567890
  URL: https://www.notion.so/abcdef1234567890...

Drop this into your config:

  cat > ~/.config/subseek/notion.yml <<'EOF'
  api_key: ntn_xxx
  database_id: abcdef1234567890abcdef1234567890
  EOF
  chmod 600 ~/.config/subseek/notion.yml
```

Run the printed `cat` command, and you're done. The DB ships with all 13 properties pre-configured — including emoji-tagged Pattern select options and the 6-state State workflow.

## 5. (Optional) Add the 4 views

Notion's API can't create views programmatically. Open your new DB and create these 4 manually — one-time, 2 minutes:

| View | Type | Group / Sort | Filter |
|---|---|---|---|
| 🔥 Hot list | Board | Group by Subreddit, sort Fit desc | State = Hot |
| 🧪 Drafting queue | Table | sort Surfaced on desc | State = Drafting |
| 📊 Pattern pulse | Board | Group by Pattern | Surfaced on within 7 days |
| ♻️ Replied | Table | sort Surfaced on desc | State = Replied |

## 6. Verify

```bash
/subseek:run
```

Surfaces should appear inline AND in your Notion board. If only inline, check `~/.config/subseek/notion.yml` has both `api_key` and `database_id` set.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `unauthorized` on setup | Integration not connected to parent page | Page → Connections → Add `subseek` |
| `object_not_found` on setup | Wrong page ID, or page in different workspace than integration | Re-copy ID from page URL; confirm same workspace |
| Setup succeeds but `/subseek:run` doesn't sync | `notion.yml` missing or wrong path | Run setup script output's `cat > ...` command exactly |
| Rate-limited (429) | Daily volume > 3 req/sec sustained | Non-issue at normal volume; if it persists, lower `--daily-cap` |

## Privacy

- Your `NOTION_API_KEY` lives in `~/.config/subseek/notion.yml` with mode 0600 (owner-only)
- The plugin only writes to the database you supplied — it never touches other workspace content
- No telemetry; no third-party calls; the only Notion API calls are `databases.create` (once, this script) + `pages.create` (every `/subseek:run`) + `pages.update` (decay job)
