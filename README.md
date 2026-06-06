# daily-brief

Automated morning brief for the Raspberry Pi.

**Pipeline:** Todoist + Google Calendar → Claude Code → network printer

Runs on a cron schedule. Fetches your tasks and events, invokes Claude Code
to produce a daily brief in your usual daily-prep format, and prints it.

---

## Prerequisites

On the Pi:

```bash
# Python 3.13 (ships with Pi OS Trixie)
python3 --version

# Claude Code
npm install -g @anthropic-ai/claude-code

# CUPS for printing
sudo apt install cups cups-client
```

---

## Setup

### 1. Create venv and install dependencies

```bash
cd ~/daily-brief
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
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
- `DATA_DIR` — where to store dated data/brief files (default: `./brief_output`)
- `TIMEZONE` — your local timezone (default: `America/Chicago`)

### 3. Google OAuth (one-time)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → Enable **Google Calendar API**
3. Create OAuth credentials: **Desktop app** type
4. Download the credentials and copy `client_id` and `client_secret` into `.env`
5. The setup script listens on port 3456 for the OAuth callback. Since the Pi is headless,
   open an SSH tunnel from your Mac **before** running the script:

```bash
# On your Mac — keep this terminal open
ssh -L 3456:localhost:3456 pi@<pi-ip>
```

6. In a second terminal (SSH'd into the Pi), run the auth script:

```bash
source venv/bin/activate
python setup_gcal_auth.py
```

7. Copy the URL it prints, open it in your Mac's browser, and authorize.
   The callback will tunnel back through port 3456 to the Pi automatically.

The script writes the refresh token to `.env`. You only need to do this once — the token auto-refreshes.

### 4. Set up the printer

#### Install CUPS

```bash
sudo apt update
sudo apt install -y cups cups-client

# Allow your user to manage printers without sudo
sudo usermod -aG lpadmin pi

# Enable and start CUPS
sudo systemctl enable cups
sudo systemctl start cups
```

#### Find your printer's IP address

Check your router's admin page, or scan the local network:

```bash
# Option A: check router's DHCP table at 192.168.1.1 (or similar)

# Option B: scan for IPP printers
lpinfo -v | grep -i ipp

# Option C: nmap scan (install with: sudo apt install nmap)
sudo nmap -p 631 192.168.1.0/24 --open
```

#### Add the printer to CUPS

```bash
# Add a network printer by IP (IPP is standard for most modern printers)
sudo lpadmin -p "MyPrinter" -E -v ipp://192.168.1.x/ipp/print -m everywhere

# Verify it was added
lpstat -p -d

# Send a test page
lp -d "MyPrinter" /etc/motd
```

Replace `MyPrinter` with a short name you choose (no spaces) and `192.168.1.x` with your printer's IP.

#### Set PRINTER_NAME in .env

```bash
# Whatever name you used in lpadmin -p above
PRINTER_NAME=MyPrinter
```

### 5. Authenticate Claude Code

```bash
claude  # follow login prompts on first run
```

---

## Manual test run

```bash
source venv/bin/activate

# Test each step individually:
python fetch_data.py
python generate_brief.py
python print_brief.py

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

> **Note:** Cron runs in a minimal environment. The shell script activates the venv
> automatically (`source venv/bin/activate`), so Python and all dependencies are on PATH.
> If `claude` still isn't found, add its full path:
> ```cron
> PATH=/usr/local/bin:/usr/bin:/bin
> ```
> Check with `which claude` in a normal terminal session.

---

## Logs

Each run logs to `logs/YYYY-MM-DD.log`. The cron output also appends to `logs/cron.log`.

```bash
# Watch today's log
tail -f ~/daily-brief/logs/$(date +%Y-%m-%d).log
```

---

## Data retention

Old files in `brief_output/` accumulate over time. To keep the last 30 days:

```bash
# Add to crontab alongside the brief job:
0 7 * * * find /home/pi/daily-brief/brief_output -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `claude: command not found` in cron | Add full path to cron PATH, see above |
| `No refresh token returned` in setup | Revoke app at https://myaccount.google.com/permissions and re-run |
| Printer not found | Run `lpstat -p` and verify `PRINTER_NAME` matches exactly |
| Brief is empty | Check `brief_output/YYYY-MM-DD/prompt.txt` and `logs/YYYY-MM-DD.log` |
| Google auth expired | Refresh tokens last indefinitely unless revoked; if it fails, re-run `setup_gcal_auth.py` |
