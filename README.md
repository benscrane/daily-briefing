# daily-brief

Automated morning brief for the Raspberry Pi.

**Pipeline:** Todoist + Google Calendar → Claude Code → network printer

Runs on a cron schedule. Fetches your tasks and events, invokes Claude Code
to produce a daily brief in your usual daily-prep format, and prints it.

---

## Prerequisites

On the Pi:

```bash
# Node 18+
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
nvm install 20

# Claude Code
npm install -g @anthropic-ai/claude-code

# CUPS for printing
sudo apt install cups cups-client
```

---

## Setup

### 1. Install dependencies

```bash
cd ~/daily-brief
npm install
```

### 2. Configure environment

```bash
cp .env.example .env
nano .env
```

Fill in:
- `TODOIST_API_TOKEN` — from https://app.todoist.com/app/settings/integrations/developer
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` — see Google OAuth setup below
- `PRINTER_NAME` — run `lpstat -p` to find yours
- `DATA_DIR` — where to store dated data/brief files (default: `./data`)
- `TIMEZONE` — your local timezone (default: `America/Chicago`)

### 3. Google OAuth (one-time)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → Enable **Google Calendar API**
3. Create OAuth credentials: **Desktop app** type
4. Download the credentials and copy `client_id` and `client_secret` into `.env`
5. Run the auth setup script:

```bash
npx ts-node src/setup-gcal-auth.ts
```

This opens a browser, asks you to authorize, and writes the refresh token to `.env`.
You only need to do this once — the token auto-refreshes.

### 4. Find your printer

```bash
# List known printers
lpstat -p -d

# Discover network printers
lpinfo -v | grep -i ipp

# Add a network printer (if needed)
sudo lpadmin -p "MyPrinter" -E -v ipp://192.168.1.x/ipp/print -m everywhere
```

Set `PRINTER_NAME` in `.env` to the name shown by `lpstat -p`.

### 5. Authenticate Claude Code

```bash
claude  # follow login prompts on first run
```

---

## Manual test run

```bash
# Test each step individually:
npx ts-node src/fetch-data.ts
npx ts-node src/generate-brief.ts
npx ts-node src/print-brief.ts

# Or run the full pipeline:
bash daily-brief.sh
```

Output files land in `$DATA_DIR/YYYY-MM-DD/`:
- `data.json` — raw fetched data
- `prompt.txt` — prompt sent to Claude
- `brief.md` — generated brief (markdown)
- `brief.txt` — print-ready plain text

---

## Cron setup

```bash
crontab -e
```

Add one of these lines:

```cron
# Weekdays at 6:30 AM
30 6 * * 1-5 /home/pi/daily-brief/daily-brief.sh >> /home/pi/daily-brief/logs/cron.log 2>&1

# Every day at 6:30 AM
30 6 * * * /home/pi/daily-brief/daily-brief.sh >> /home/pi/daily-brief/logs/cron.log 2>&1
```

> **Note:** Cron runs in a minimal environment. The script sources nvm automatically,
> but if `claude` or `node` still isn't found, add the full path:
> ```cron
> PATH=/home/pi/.nvm/versions/node/v20.x.x/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
> ```
> Check the path with `which claude` in a normal terminal session.

---

## Logs

Each run logs to `logs/YYYY-MM-DD.log`. The cron output also appends to `logs/cron.log`.

```bash
# Watch today's log
tail -f ~/daily-brief/logs/$(date +%Y-%m-%d).log
```

---

## Data retention

Old files in `data/` accumulate over time. To keep the last 30 days:

```bash
# Add to crontab alongside the brief job:
0 7 * * * find /home/pi/daily-brief/data -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `claude: command not found` in cron | Add full nvm path to cron PATH, see above |
| `No refresh token returned` in setup | Revoke app at https://myaccount.google.com/permissions and re-run |
| Printer not found | Run `lpstat -p` and verify `PRINTER_NAME` matches exactly |
| Brief is empty | Check `data/YYYY-MM-DD/prompt.txt` and `logs/YYYY-MM-DD.log` |
| Google auth expired | Refresh tokens last indefinitely unless revoked; if it fails, re-run `setup-gcal-auth.ts` |