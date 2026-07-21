#!/usr/bin/env python3
"""
fetch_data.py

Pulls today's Todoist tasks (including overdue) and Google Calendar events
(today + tomorrow AM) then writes a dated JSON file to DATA_DIR.

Output: DATA_DIR/YYYY-MM-DD/data.json
"""

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from google.auth.exceptions import RefreshError

from common import DATA_DIR, TIMEZONE, TZ, brief_date
from gcal_client import build_calendar_service

TODOIST_TOKEN = os.environ.get("TODOIST_API_TOKEN", "")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN", "")

CONFIG_PATH = Path(__file__).parent / "config.json"
config = json.loads(CONFIG_PATH.read_text())
CALENDAR_IDS: list[str] = config.get("calendarIds", ["primary"])


def _require(name: str, val: str) -> None:
    if not val:
        print(f"[fetch-data] Missing env var: {name}", file=sys.stderr)
        sys.exit(1)


def fetch_todoist() -> dict:
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {TODOIST_TOKEN}"
    retry = Retry(
        total=4,
        backoff_factor=15,  # waits 15, 30, 60, 120s between retries
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    base = "https://api.todoist.com/api/v1"

    projects_res = session.get(f"{base}/projects", params={"limit": 200})
    projects_res.raise_for_status()
    raw_projects = projects_res.json()["results"]
    projects = {p["id"]: p["name"] for p in raw_projects}

    redox_id = next((p["id"] for p in raw_projects if p["name"] == "Redox"), None)
    work_ids: set[str] = set()
    if redox_id:
        work_ids.add(redox_id)
        changed = True
        while changed:
            changed = False
            for p in raw_projects:
                if p["id"] not in work_ids and p.get("parent_id") in work_ids:
                    work_ids.add(p["id"])
                    changed = True

    labels_res = session.get(f"{base}/labels", params={"limit": 200})
    labels_res.raise_for_status()
    labels = {la["id"]: la["name"] for la in labels_res.json()["results"]}

    today_res = session.get(
        f"{base}/tasks/filter", params={"query": "today | overdue", "limit": 200}
    )
    today_res.raise_for_status()
    today_tasks = today_res.json()["results"]

    important_res = session.get(
        f"{base}/tasks/filter", params={"query": "@important", "limit": 200}
    )
    important_res.raise_for_status()
    important_tasks = important_res.json()["results"]

    today_ids = {t["id"] for t in today_tasks}
    important_only = [t for t in important_tasks if t["id"] not in today_ids]

    return {
        "todayAndOverdue": today_tasks,
        "importantUndated": important_only,
        "projects": projects,
        "labels": labels,
        "workProjectIds": sorted(work_ids),
    }


def fetch_calendar(today: str, tomorrow: str) -> dict:
    service = build_calendar_service()

    today_start = datetime.fromisoformat(f"{today}T00:00:00").replace(tzinfo=TZ).isoformat()
    today_end = datetime.fromisoformat(f"{today}T23:59:59").replace(tzinfo=TZ).isoformat()
    tomorrow_start = datetime.fromisoformat(f"{tomorrow}T06:00:00").replace(tzinfo=TZ).isoformat()
    tomorrow_end = datetime.fromisoformat(f"{tomorrow}T11:00:00").replace(tzinfo=TZ).isoformat()

    today_events: list[dict] = []
    tomorrow_am_events: list[dict] = []

    for cal_id in CALENDAR_IDS:
        res = (
            service.events()
            .list(
                calendarId=cal_id,
                timeMin=today_start,
                timeMax=today_end,
                singleEvents=True,
                orderBy="startTime",
                maxResults=50,
            )
            .execute()
        )
        today_events.extend(res.get("items", []))

        res = (
            service.events()
            .list(
                calendarId=cal_id,
                timeMin=tomorrow_start,
                timeMax=tomorrow_end,
                singleEvents=True,
                orderBy="startTime",
                maxResults=20,
            )
            .execute()
        )
        tomorrow_am_events.extend(res.get("items", []))

    def start_key(e: dict) -> str:
        s = e.get("start", {})
        return s.get("dateTime") or s.get("date") or ""

    today_events.sort(key=start_key)
    tomorrow_am_events.sort(key=start_key)

    return {"today": today_events, "tomorrowAM": tomorrow_am_events}


def main() -> None:
    _require("TODOIST_API_TOKEN", TODOIST_TOKEN)
    _require("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID)
    _require("GOOGLE_CLIENT_SECRET", GOOGLE_CLIENT_SECRET)
    _require("GOOGLE_REFRESH_TOKEN", GOOGLE_REFRESH_TOKEN)

    today = brief_date()
    tomorrow = (date.fromisoformat(today) + timedelta(days=1)).isoformat()

    print(f"[fetch-data] Fetching data for {today} (tz: {TIMEZONE})")

    todoist = fetch_todoist()
    calendar = fetch_calendar(today, tomorrow)

    output = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "date": today,
        "timezone": TIMEZONE,
        "todoist": todoist,
        "calendar": calendar,
    }

    out_dir = DATA_DIR / today
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "data.json"
    out_path.write_text(json.dumps(output, indent=2))

    print(f"[fetch-data] ✓ Wrote {out_path}")
    print(
        f"[fetch-data]   {len(todoist['todayAndOverdue'])} tasks today/overdue, "
        f"{len(todoist['importantUndated'])} @important undated, "
        f"{len(calendar['today'])} events today, "
        f"{len(calendar['tomorrowAM'])} events tomorrow AM"
    )


if __name__ == "__main__":
    try:
        main()
    except requests.exceptions.RetryError as e:
        print(f"[fetch-data] RETRY EXHAUSTED: {e}", file=sys.stderr)
        sys.exit(1)
    except RefreshError as e:
        print(f"[fetch-data] GOOGLE AUTH ERROR: {e}", file=sys.stderr)
        print(
            "[fetch-data] Google rejected the stored refresh token. This usually means "
            "it expired (OAuth apps in 'Testing' status expire tokens after 7 days) or "
            "was revoked. Publish the app to Production in the Google Cloud console, "
            "then re-run setup_gcal_auth.py to get a new token.",
            file=sys.stderr,
        )
        sys.exit(1)
    except requests.HTTPError as e:
        print(f"[fetch-data] HTTP ERROR: {e}", file=sys.stderr)
        if e.response is not None:
            print(f"  status: {e.response.status_code}", file=sys.stderr)
            print(f"  url: {e.response.url}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[fetch-data] ERROR: {e}", file=sys.stderr)
        sys.exit(1)
