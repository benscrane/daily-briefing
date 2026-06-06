#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# daily-brief.sh
#
# Orchestrates the full daily brief pipeline:
#   1. fetch_data.py     — pull Todoist + Google Calendar
#   2. generate_brief.py — invoke Claude Code to produce the brief
#   3. print_brief.py    — send to network printer
#
# Cron example (runs at 6:30 AM Mon–Fri):
#   30 6 * * 1-5 /home/pi/daily-brief/daily-brief.sh >> /home/pi/daily-brief/logs/cron.log 2>&1
#
# For weekend runs too:
#   30 6 * * * /home/pi/daily-brief/daily-brief.sh >> /home/pi/daily-brief/logs/cron.log 2>&1
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "${LOG_DIR}"

DATE=$(date +%Y-%m-%d)
LOG_FILE="${LOG_DIR}/${DATE}.log"

# Tee all output to a dated log file
exec > >(tee -a "${LOG_FILE}") 2>&1

echo "════════════════════════════════════════"
echo " Daily Brief — ${DATE}"
echo " Started: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "════════════════════════════════════════"

# ─── Environment ─────────────────────────────────────────────────────────────

# Activate the Python venv (contains all dependencies)
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/venv/bin/activate"

# Verify dependencies
for cmd in python claude lp; do
  if ! command -v "${cmd}" &>/dev/null; then
    echo "ERROR: '${cmd}' not found in PATH. Aborting."
    echo "  python: check venv at ${SCRIPT_DIR}/venv"
    echo "  claude: npm install -g @anthropic-ai/claude-code"
    echo "  lp:     sudo apt install cups cups-client"
    exit 1
  fi
done

cd "${SCRIPT_DIR}"

# ─── Step 1: Fetch data ───────────────────────────────────────────────────────

echo ""
echo "── Step 1/3: Fetching Todoist + Calendar data ──"
if ! python fetch_data.py; then
  echo "ERROR: fetch_data.py failed. Aborting."
  exit 1
fi

# ─── Step 2: Generate brief ───────────────────────────────────────────────────

echo ""
echo "── Step 2/3: Generating brief with Claude Code ──"
if ! python generate_brief.py; then
  echo "ERROR: generate_brief.py failed. Aborting."
  exit 1
fi

# ─── Step 3: Print ───────────────────────────────────────────────────────────

echo ""
echo "── Step 3/3: Sending to printer ──"
if ! python print_brief.py; then
  echo "ERROR: print_brief.py failed."
  # Don't exit 1 — brief was generated even if print failed
fi

# ─── Done ─────────────────────────────────────────────────────────────────────

echo ""
echo "════════════════════════════════════════"
echo " Done: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "════════════════════════════════════════"
