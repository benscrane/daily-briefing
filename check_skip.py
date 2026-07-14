#!/usr/bin/env python3
"""
check_skip.py

Checks today's Google Calendar events, across every calendar configured in
config.json, for an event titled "No Brief" (case-insensitive, exact match).
If one is found, the rest of the pipeline should be skipped for today.

Exit codes:
  0 — no skip event found, proceed with the pipeline
  1 — error checking the calendar
  2 — skip event found, skip today's pipeline
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

from gcal_client import build_calendar_service

load_dotenv()

TIMEZONE = os.environ.get("TIMEZONE", "America/Chicago")
SKIP_EVENT_TITLE = os.environ.get("SKIP_EVENT_TITLE", "No Brief")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN", "")

CONFIG_PATH = Path(__file__).parent / "config.json"
config = json.loads(CONFIG_PATH.read_text())
CALENDAR_IDS: list[str] = config.get("calendarIds", ["primary"])


def _require(name: str, val: str) -> None:
    if not val:
        print(f"[check-skip] Missing env var: {name}", file=sys.stderr)
        sys.exit(1)


def has_skip_event(today: str) -> bool:
    service = build_calendar_service()
    tz = ZoneInfo(TIMEZONE)
    time_min = datetime.fromisoformat(f"{today}T00:00:00").replace(tzinfo=tz).isoformat()
    time_max = datetime.fromisoformat(f"{today}T23:59:59").replace(tzinfo=tz).isoformat()

    target = SKIP_EVENT_TITLE.strip().casefold()

    for cal_id in CALENDAR_IDS:
        res = (
            service.events()
            .list(
                calendarId=cal_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                maxResults=50,
            )
            .execute()
        )
        for event in res.get("items", []):
            summary = (event.get("summary") or "").strip().casefold()
            if summary == target:
                return True
    return False


def main() -> None:
    _require("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID)
    _require("GOOGLE_CLIENT_SECRET", GOOGLE_CLIENT_SECRET)
    _require("GOOGLE_REFRESH_TOKEN", GOOGLE_REFRESH_TOKEN)

    tz = ZoneInfo(TIMEZONE)
    today = datetime.now(tz).strftime("%Y-%m-%d")

    if has_skip_event(today):
        print(f'[check-skip] "{SKIP_EVENT_TITLE}" event found for {today} — skipping brief.')
        sys.exit(2)

    print(f"[check-skip] No skip event found for {today} — proceeding.")


if __name__ == "__main__":
    try:
        main()
    except RefreshError as e:
        print(f"[check-skip] GOOGLE AUTH ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except HttpError as e:
        print(f"[check-skip] CALENDAR API ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[check-skip] ERROR: {e}", file=sys.stderr)
        sys.exit(1)
