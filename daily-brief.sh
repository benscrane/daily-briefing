#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# daily-brief.sh
#
# Orchestrates the full daily brief pipeline:
#   1. fetch-data.ts   — pull Todoist + Google Calendar
#   2. generate-brief.ts — invoke Claude Code to produce the brief
#   3. print-brief.ts  — send to network printer
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

# Load nvm / node if installed via nvm (common on Pi)
export NVM_DIR="${HOME}/.nvm"
if [ -s "${NVM_DIR}/nvm.sh" ]; then
  # shellcheck source=/dev/null
  source "${NVM_DIR}/nvm.sh"
fi

# Or if node is in a non-standard path, add it:
# export PATH="/usr/local/bin:${PATH}"

# Verify dependencies
for cmd in node npx claude lp; do
  if ! command -v "${cmd}" &>/dev/null; then
    echo "ERROR: '${cmd}' not found in PATH. Aborting."
    echo "  node/npx: check nvm or apt install nodejs"
    echo "  claude:   check 'npm install -g @anthropic-ai/claude-code'"
    echo "  lp:       sudo apt install cups cups-client"
    exit 1
  fi
done

cd "${SCRIPT_DIR}"

# Install deps if node_modules missing (first run or after clean)
if [ ! -d "node_modules" ]; then
  echo "[setup] Installing npm dependencies..."
  npm install --silent
fi

# ─── Step 1: Fetch data ───────────────────────────────────────────────────────

echo ""
echo "── Step 1/3: Fetching Todoist + Calendar data ──"
if ! npx ts-node src/fetch-data.ts; then
  echo "ERROR: fetch-data.ts failed. Aborting."
  exit 1
fi

# ─── Step 2: Generate brief ───────────────────────────────────────────────────

echo ""
echo "── Step 2/3: Generating brief with Claude Code ──"
if ! npx ts-node src/generate-brief.ts; then
  echo "ERROR: generate-brief.ts failed. Aborting."
  exit 1
fi

# ─── Step 3: Print ───────────────────────────────────────────────────────────

echo ""
echo "── Step 3/3: Sending to printer ──"
if ! npx ts-node src/print-brief.ts; then
  echo "ERROR: print-brief.ts failed."
  # Don't exit 1 — brief was generated even if print failed
  # You can add an email/notification fallback here
fi

# ─── Done ─────────────────────────────────────────────────────────────────────

echo ""
echo "════════════════════════════════════════"
echo " Done: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "════════════════════════════════════════"