# daily-brief

Automated morning brief for the Raspberry Pi.

**Pipeline:** Todoist + Google Calendar → Claude via AWS Bedrock → network printer

Runs on a cron schedule. Fetches your tasks and events, calls Claude on Amazon
Bedrock to produce a daily brief in your usual daily-prep format, and prints it.

---

## Prerequisites

On the Pi:

```bash
# Python 3.13 (ships with Pi OS Trixie)
python3 --version

# CUPS for printing
sudo apt install cups cups-client
```

An **AWS account** with Bedrock access is required. Enable model access for Claude Sonnet
(or whichever model you want) in the [Bedrock console](https://console.aws.amazon.com/bedrock/)
under **Model access**. Create an IAM user with `AmazonBedrockFullAccess` (or a scoped-down
policy allowing `bedrock:InvokeModel` / `bedrock:Converse`) and note the access key and secret.

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
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` — IAM credentials with Bedrock access
- `AWS_REGION` — Bedrock region (default: `us-east-1`)
- `BEDROCK_MODEL_ID` — model to use (default: `us.anthropic.claude-sonnet-4-6`); the `us.` prefix routes via the US cross-region inference profile
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

### 5. Make the script executable

```bash
chmod +x ~/daily-briefing/daily-brief.sh
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
./daily-brief.sh
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
30 6 * * 1-5 /home/belle/daily-briefing/daily-brief.sh

# Every day at 6:30 AM
30 6 * * * /home/belle/daily-briefing/daily-brief.sh
```

> **Note:** Cron runs in a minimal environment. The shell script activates the venv
> automatically (`source venv/bin/activate`), so Python and all dependencies (including
> `boto3`) are on PATH. AWS credentials are read from `.env` via `set -a; source .env; set +a`
> at the top of the script — no extra cron configuration needed.

---

## Logs

Each run logs to `logs/YYYY-MM-DD.log` inside the project directory. No redirect needed in the cron entry — the script handles its own logging via `tee`. If the `logs/` directory isn't writable the script falls back to `/tmp/daily-brief-logs/`.

```bash
# Watch today's log
tail -f ~/daily-briefing/logs/$(date +%Y-%m-%d).log
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
| `Permission denied` running the script | `chmod +x ~/daily-briefing/daily-brief.sh` |
| `Bedrock call failed: ... AccessDeniedException` | Verify IAM credentials and that model access is enabled in the Bedrock console |
| `Bedrock call failed: ... ValidationException` | Check `BEDROCK_MODEL_ID` — the `us.` prefix is required for US cross-region inference profiles |
| `No refresh token returned` in setup | Revoke app at https://myaccount.google.com/permissions and re-run |
| Printer not found | Run `lpstat -p` and verify `PRINTER_NAME` matches exactly |
| Brief is empty | Check `brief_output/YYYY-MM-DD/prompt.txt` and `logs/YYYY-MM-DD.log` |
| Google auth expired | Refresh tokens last indefinitely unless revoked; if it fails, re-run `setup_gcal_auth.py` |
