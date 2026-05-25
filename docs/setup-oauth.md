# Reddit OAuth setup

`reddit-engage` works without OAuth (falls back to logged-out `/new.json`) but registering a Reddit app unlocks:

- **10x rate budget** — 100 QPM authenticated vs ~10 QPM rate-shaped on the public path
- **Identity scope** — needed for Phase 5 postmortem (auto-detect your own replies)
- **Cloudflare immunity** — no anti-bot challenges on datacenter IPs

Total time: ~5 minutes. Reddit doesn't review personal-use script apps.

## 1. Create the app

Open https://www.reddit.com/prefs/apps while logged into the account `reddit-engage` will act on behalf of.

Click **"create another app..."** at the bottom and fill in:

| Field | Value |
|---|---|
| **name** | `reddit-engage` (anything you want) |
| **app type** | **`script`** ← important, not "web app" or "installed" |
| **description** | leave blank |
| **about url** | leave blank |
| **redirect uri** | `http://localhost` |

Click **create app**. Reddit shows the new app card.

## 2. Copy the credentials

The card looks like this:

```
reddit-engage              [edit]   [delete]
personal use script
<14-character client ID>             ← this is your client_id
secret: <27-character string>         ← click "edit" if hidden
```

You need three values:

- The **14-char string** under the app name → `client_id`
- The **secret** → `client_secret`
- Your **Reddit username** (without `u/` prefix) → `username`

## 3. Drop them in oauth.json

```bash
mkdir -p ~/.config/reddit-engage
cat > ~/.config/reddit-engage/oauth.json <<'EOF'
{
  "client_id":     "PUT_14_CHAR_STRING_HERE",
  "client_secret": "PUT_27_CHAR_SECRET_HERE",
  "username":      "your_reddit_username",
  "user_agent":    "reddit-engage/0.1 by /u/your_reddit_username"
}
EOF
chmod 600 ~/.config/reddit-engage/oauth.json
```

The `chmod 600` step is important — the file holds secrets in plaintext.

> **Alternative: plugin user config.** If you installed via `/plugin install dancolta/reddit-engage`, Claude Code already prompted you for these and stored them in your OS keychain. You only need to write `oauth.json` manually if you cloned the repo directly without going through the plugin install flow.

## 4. Verify

```bash
cd ~/Work/reddit-engage
PYTHONPATH=engine python3 -c "
from reddit_engage.lib import reddit_oauth
print('has_oauth:', reddit_oauth.has_oauth())
print('first 3 posts from r/sales:')
for p in reddit_oauth.fetch_delta('sales', None, max_limit=3):
    print(' ', p['id'], '|', p['title'][:60])
"
```

Expected output:

```
has_oauth: True
first 3 posts from r/sales:
  abc123 | <a recent title>
  def456 | <another>
  ghi789 | <another>
```

If `has_oauth: False`, the script falls back to public JSON automatically — that's by design, not a failure. Confirm `~/.config/reddit-engage/oauth.json` exists and has all three required fields.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `prawcore.exceptions.OAuthException: invalid_grant` | Wrong client_secret or username | Re-copy from reddit.com/prefs/apps |
| `prawcore.exceptions.Forbidden: 403` | App type is "web app", not "script" | Delete + recreate as `script` type |
| Silent fallback to public JSON | PRAW not installed | `pip install -e '.[reddit]'` |
| `[reddit-oauth] OAuth fetch failed → falling back to public JSON: ...` | Transient (token, network) | Run again. Persistent → check credentials |

## Optional: refresh tokens

For long-running daemons or installed-app flow, swap `password`/script grant for a refresh token. See the `password` and `refresh_token` fields in [`reddit_oauth.py`](../engine/reddit_engage/lib/reddit_oauth.py). Script apps don't need this — they auth via username + client credentials directly.

## Privacy

`reddit-engage` never sends your credentials anywhere except Reddit's OAuth endpoint. The full request flow:

1. PRAW posts your credentials to `https://www.reddit.com/api/v1/access_token` (HTTPS)
2. Reddit returns a short-lived bearer token
3. Subsequent fetches use the bearer token, not the password
4. No telemetry. No third-party calls. No analytics.

The plugin source is at https://github.com/dancolta/reddit-engage — audit it.
