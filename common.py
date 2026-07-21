#!/usr/bin/env python3
"""Shared pipeline config: env loading, DATA_DIR, TIMEZONE, and the run date.

Importing this module runs load_dotenv(), so scripts that import it do not
call load_dotenv() themselves — just import common before reading env vars.
"""

import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent / "brief_output"))
TIMEZONE = os.environ.get("TIMEZONE", "America/Chicago")
TZ = ZoneInfo(TIMEZONE)


def brief_now() -> datetime:
    return datetime.now(TZ)


def brief_date() -> str:
    """The YYYY-MM-DD date this pipeline run is for.

    BRIEF_DATE env var (exported once by daily-brief.sh) pins every step of a
    run to the same folder even if the pipeline crosses midnight, and lets you
    re-run any step for a past date. Standalone runs fall back to the current
    date in TIMEZONE.
    """
    override = os.environ.get("BRIEF_DATE", "")
    if override:
        date.fromisoformat(override)  # fail fast on a malformed override
        return override
    return brief_now().strftime("%Y-%m-%d")
