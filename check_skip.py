#!/usr/bin/env python3
"""
check_skip.py

Decides whether today's brief should run, based on today's Google Calendar
events across every calendar configured in config.json. Two rules, in order:

  1. An event titled "No Brief" (case-insensitive, exact match) skips the day.
  2. Weekends (Sat/Sun) are skipped unless an event titled "Weekend Brief"
     exists, which opts that day back in. Disable this rule entirely with
     SKIP_WEEKENDS=false.

Exit codes:
  0 — proceed with the pipeline
  1 — error checking the calendar
  2 — "No Brief" event found, skip today's pipeline
  3 — weekend with no opt-in event, skip today's pipeline
"""

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

from common import TZ, brief_date
from gcal_client import build_calendar_service

SKIP_EVENT_TITLE = os.environ.get("SKIP_EVENT_TITLE", "No Brief")
RUN_EVENT_TITLE = os.environ.get("RUN_EVENT_TITLE", "Weekend Brief")
SKIP_WEEKENDS = os.environ.get("SKIP_WEEKENDS", "true").strip().lower() not in (
    "0",
    "false",
    "no",
)
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


def event_titles(today: str) -> set[str]:
    """Casefolded titles of every event on today's date, across all calendars."""
    service = build_calendar_service()
    time_min = datetime.fromisoformat(f"{today}T00:00:00").replace(tzinfo=TZ).isoformat()
    time_max = datetime.fromisoformat(f"{today}T23:59:59").replace(tzinfo=TZ).isoformat()

    titles: set[str] = set()
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
            titles.add((event.get("summary") or "").strip().casefold())
    return titles


def main() -> None:
    _require("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID)
    _require("GOOGLE_CLIENT_SECRET", GOOGLE_CLIENT_SECRET)
    _require("GOOGLE_REFRESH_TOKEN", GOOGLE_REFRESH_TOKEN)

    today = brief_date()
    titles = event_titles(today)

    # An explicit "No Brief" wins over the weekend opt-in.
    if SKIP_EVENT_TITLE.strip().casefold() in titles:
        print(f'[check-skip] "{SKIP_EVENT_TITLE}" event found for {today} — skipping brief.')
        sys.exit(2)

    if SKIP_WEEKENDS and date.fromisoformat(today).weekday() >= 5:
        if RUN_EVENT_TITLE.strip().casefold() not in titles:
            print(
                f'[check-skip] {today} is a weekend and no "{RUN_EVENT_TITLE}" event '
                "was found — skipping brief."
            )
            sys.exit(3)
        print(
            f'[check-skip] {today} is a weekend, but a "{RUN_EVENT_TITLE}" event '
            "was found — proceeding."
        )
        return

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
