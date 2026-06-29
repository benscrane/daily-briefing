#!/usr/bin/env python3
"""
print_brief.py

Reads today's brief.md, converts it to print-ready plain text,
and sends it to the configured network printer via lp/CUPS.

Requires: cups (lp command) installed on the Pi.
Install: sudo apt install cups cups-client

To find your printer name: lpstat -p -d
                            lpinfo -v  (shows network printers)
"""

import os
import re
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent / "brief_output"))
TIMEZONE = os.environ.get("TIMEZONE", "America/Chicago")
PRINTER_NAME = os.environ.get("PRINTER_NAME", "")
PRINTER_OPTIONS = os.environ.get("PRINTER_OPTIONS", "")
# Total characters per printed line and how many spaces to indent on the left.
# Content width = PRINT_LINE_WIDTH - PRINT_LEFT_MARGIN.
PRINT_LINE_WIDTH = int(os.environ.get("PRINT_LINE_WIDTH", "72"))
PRINT_LEFT_MARGIN = int(os.environ.get("PRINT_LEFT_MARGIN", "4"))

_BOX_CHARS = frozenset("═─╔╗╚╝║")


def markdown_to_text(md: str) -> str:
    def h2_replace(m: re.Match) -> str:
        title = m.group(1)
        return f"\n{title.upper()}"

    def h3_replace(m: re.Match) -> str:
        title = m.group(1)
        line = "─" * min(len(title) + 2, 50)
        return f"\n{title}\n{' ' * PRINT_LEFT_MARGIN}{line}"

    text = re.sub(r"^## (.+)$", h2_replace, md, flags=re.MULTILINE)
    text = re.sub(r"^### (.+)$", h3_replace, text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"^```.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def add_print_wrapper(text: str, date: str) -> str:
    now = datetime.now(ZoneInfo(TIMEZONE))
    printed_at = now.strftime("%-I:%M %p")

    banner = "\n".join([
        f"DAILY BRIEF — {date}",
        f"Printed at {printed_at}",
        "",
        "",
    ])

    return banner + text


def wrap_for_print(text: str) -> str:
    """Word-wrap text to fit the page and add a left margin.

    Lines containing box-drawing characters (headers, banners) are passed
    through unchanged.  Bullet lines get a hanging indent so the text of
    long bullets aligns under the first word, not under the bullet marker.
    Words are never split across lines.
    """
    indent = " " * PRINT_LEFT_MARGIN
    content_width = PRINT_LINE_WIDTH - PRINT_LEFT_MARGIN
    out = []
    for line in text.splitlines():
        # Box-drawing and blank lines pass through as-is.
        if not line.strip() or _BOX_CHARS.intersection(line):
            out.append(line)
            continue
        # Detect a leading bullet marker so continuation lines align under
        # the text, not under the marker itself.
        m = re.match(r"^([•\-\*]\s+)", line.lstrip())
        subsequent = indent + " " * len(m.group(1)) if m else indent
        out.append(textwrap.fill(
            line.strip(),
            width=content_width,
            initial_indent=indent,
            subsequent_indent=subsequent,
            break_long_words=False,
            break_on_hyphens=False,
        ))
    return "\n".join(out)


def main() -> None:
    if not PRINTER_NAME:
        print("[print-brief] PRINTER_NAME not set in .env", file=sys.stderr)
        print("[print-brief] Run `lpstat -p` to find your printer name.", file=sys.stderr)
        sys.exit(1)

    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d")

    out_dir = DATA_DIR / today
    brief_path = out_dir / "brief.md"
    print_path = out_dir / "brief.txt"

    if not brief_path.exists():
        print(f"[print-brief] No brief found at {brief_path}", file=sys.stderr)
        print("[print-brief] Run generate_brief.py first.", file=sys.stderr)
        sys.exit(1)

    markdown = brief_path.read_text()
    plain_text = markdown_to_text(markdown)
    print_ready = wrap_for_print(add_print_wrapper(plain_text, today))

    print_path.write_text(print_ready)
    print(f"[print-brief] Wrote print-ready text to {print_path}")

    try:
        subprocess.run(
            ["lpstat", "-p", PRINTER_NAME],
            capture_output=True,
            timeout=10,
        )
    except Exception:
        print(f'[print-brief] ⚠ Could not verify printer "{PRINTER_NAME}" — attempting anyway.')

    cmd = ["lp", "-d", PRINTER_NAME, "-t", f"Daily Brief {today}", str(print_path)]
    if PRINTER_OPTIONS:
        cmd[2:2] = PRINTER_OPTIONS.split()

    print(f"[print-brief] Sending to printer: {PRINTER_NAME}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print("[print-brief] Print failed:", file=sys.stderr)
            print(result.stderr or result.stdout, file=sys.stderr)
            sys.exit(1)
        print(f"[print-brief] ✓ {result.stdout.strip()}")
    except subprocess.TimeoutExpired:
        print("[print-brief] ERROR: lp command timed out.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[print-brief] ERROR: {e}", file=sys.stderr)
        sys.exit(1)
