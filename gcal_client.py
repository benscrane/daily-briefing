#!/usr/bin/env python3
"""
gcal_client.py

Shared Google Calendar auth helper for fetch_data.py and check_skip.py.
"""

import os

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN", "")


def build_calendar_service():
    creds = Credentials(
        token=None,
        refresh_token=GOOGLE_REFRESH_TOKEN,
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/calendar.readonly"],
    )
    return build("calendar", "v3", credentials=creds)
