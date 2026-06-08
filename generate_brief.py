#!/usr/bin/env python3
"""
generate_brief.py

Reads today's data.json, builds the work-task list, personal-task list, and
calendar timeline directly from the data (deterministic — identical structure
every day), then calls Claude via the Amazon Bedrock Converse API for a short
recommendations note. Combines both into the final brief.

Output: DATA_DIR/YYYY-MM-DD/brief.md
"""

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent / "brief_output"))
TIMEZONE = os.environ.get("TIMEZONE", "America/Chicago")

# Bedrock config — BEDROCK_MODEL_ID uses the US cross-region inference profile
# ("us." prefix) by default; override to experiment with other models.
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
MAX_TOKENS = int(os.environ.get("BEDROCK_MAX_TOKENS", "1024"))

PRIORITY_LABELS = {4: "P1", 3: "P2", 2: "P3", 1: "P4"}

# Time-estimate heuristic, applied in order: a matching label wins outright,
# otherwise the task's leading verb picks a bucket, otherwise ~30m.
LABEL_ESTIMATES = {"15min": 15, "30min": 30, "1hour": 60}
VERB_ESTIMATES = (
    (15, ("submit", "send", "file", "ping", "repull")),
    (30, ("review", "scope", "check", "pull", "read")),
    (60, ("create", "draft", "build", "write", "work on")),
    (75, ("plan", "put together", "one-pager", "proposal")),
)


def estimate_minutes(task: dict) -> int:
    for label in task.get("labels") or []:
        if label in LABEL_ESTIMATES:
            return LABEL_ESTIMATES[label]
    content = (task.get("content") or "").strip().lower()
    for minutes, verbs in VERB_ESTIMATES:
        if any(content.startswith(verb) for verb in verbs):
            return minutes
    return 30


def format_task_line(task: dict, today: str) -> str:
    flags = []

    priority_label = PRIORITY_LABELS.get(task.get("priority"), "P4")
    if priority_label != "P4":
        flags.append(f"[{priority_label}]")
    if "important" in (task.get("labels") or []):
        flags.append("[@important]")
    flags.append(f"(~{estimate_minutes(task)}m)")

    due = task.get("due") or {}
    if due.get("date") and due["date"] < today:
        flags.append("[overdue]")

    deadline = task.get("deadline") or {}
    if deadline.get("date") and deadline["date"] < today:
        days_ago = (date.fromisoformat(today) - date.fromisoformat(deadline["date"])).days
        flags.append(f"[deadline expired {deadline['date']} ({days_ago} days ago)]")

    return f"- **{task['content']}** " + " ".join(flags)


def render_task_list(title: str, tasks: list[dict], today: str) -> str:
    lines = [f"### {title}"]
    if not tasks:
        lines.append("- Nothing scheduled.")
    else:
        ranked = sorted(tasks, key=lambda t: (-(t.get("priority") or 1), t.get("content") or ""))
        lines.extend(format_task_line(t, today) for t in ranked)
    return "\n".join(lines)


def format_event_line(event: dict, tz: ZoneInfo) -> str:
    summary = event.get("summary", "(untitled)")
    location = event.get("location", "")
    start = event.get("start", {})
    end = event.get("end", {})

    if "dateTime" in start:
        start_dt = datetime.fromisoformat(start["dateTime"]).astimezone(tz)
        end_dt = datetime.fromisoformat(end["dateTime"]).astimezone(tz)
        line = f"- {start_dt:%H:%M}–{end_dt:%H:%M}  {summary}"
    else:
        line = f"- All day       {summary}"

    if location:
        line += f"  ({location})"
    return line


def render_timeline(events: list[dict], tz: ZoneInfo) -> str:
    lines = ["### Today's schedule"]
    if not events:
        lines.append("- Nothing on the calendar.")
    else:
        lines.extend(format_event_line(e, tz) for e in events)
    return "\n".join(lines)


def build_recommendations_prompt(data_json: str, today: str, weekday: str, sections: str) -> str:
    return f"""You are Ben's executive assistant writing the recommendations note at the bottom of his daily brief.

Today is {today} ({weekday}). Timezone: {TIMEZONE}.

The work-task list, personal-task list, and calendar timeline below are FINAL — they were already
built and printed elsewhere in the brief. Do not repeat them, reformat them, or contradict them.

<finalized-sections>
{sections}
</finalized-sections>

Here is the full underlying data, for numbers and details not shown above (postponed_count,
deadline dates, tomorrow's morning calendar, transparency, etc.):

<data>
{data_json}
</data>

<instructions>
Write ONLY a short, direct recommendations note — at most 5 bullets. Skip anything that doesn't
genuinely apply; a light day should produce a short note, not padding. Never invent a number —
only cite figures that actually appear in the data.

Consider, in rough priority order:
- Overcommitment: if the listed tasks' estimated minutes clearly exceed the free time between
  today's opaque (transparency != "transparent") calendar events, say so with the numbers and name
  1-2 drop candidates (lowest priority / largest estimate, both already in the lists above).
- What to tackle first, and why — one sentence, pointing at a specific task already in the lists above.
- Stale deadlines: any task where deadline.date is before {today} — name it with the days-ago count.
- Chronic postponers: any task with postponed_count >= 10 — name it with the count.
- Tomorrow-AM prep gap: a calendar.tomorrowAM event where Ben is presenting or external/customer
  attendees are present, and no matching prep task exists in today's lists — flag it in one line.

Output format — exactly this, nothing else:

### Recommendations
- ...
- ...

Tone: blunt, specific, skim-friendly. No questions, no preamble, no closing remarks, no emojis.
</instructions>"""


def main() -> None:
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d")
    weekday = now.strftime("%A")

    out_dir = DATA_DIR / today
    data_path = out_dir / "data.json"
    brief_path = out_dir / "brief.md"

    if not data_path.exists():
        print(f"[generate-brief] No data file found at {data_path}", file=sys.stderr)
        print("[generate-brief] Run fetch_data.py first.", file=sys.stderr)
        sys.exit(1)

    data_json = data_path.read_text()
    data = json.loads(data_json)

    todoist = data["todoist"]
    work_ids = set(todoist.get("workProjectIds") or [])
    tasks = todoist.get("todayAndOverdue") or []
    work_tasks = [t for t in tasks if t.get("project_id") in work_ids]
    personal_tasks = [t for t in tasks if t.get("project_id") not in work_ids]

    work_section = render_task_list("Work tasks", work_tasks, today)
    personal_section = render_task_list("Personal tasks", personal_tasks, today)
    timeline_section = render_timeline(data["calendar"].get("today") or [], tz)
    sections = "\n\n".join([work_section, personal_section, timeline_section])

    prompt = build_recommendations_prompt(data_json, today, weekday, sections)
    prompt_path = out_dir / "prompt.txt"
    prompt_path.write_text(prompt)

    print(f"[generate-brief] Invoking Bedrock ({BEDROCK_MODEL_ID}) for {today}...")

    client = boto3.client(
        "bedrock-runtime",
        region_name=AWS_REGION,
        config=Config(read_timeout=300, retries={"max_attempts": 3}),
    )

    try:
        resp = client.converse(
            modelId=BEDROCK_MODEL_ID,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": MAX_TOKENS},
        )
    except (BotoCoreError, ClientError) as e:
        print(f"[generate-brief] ERROR: Bedrock call failed: {e}", file=sys.stderr)
        sys.exit(1)

    recommendations = resp["output"]["message"]["content"][0]["text"].strip()

    header = f"## Daily Prep — {weekday}, {now.strftime('%B %-d')}"
    brief = "\n\n".join([header, work_section, personal_section, timeline_section, recommendations])

    brief_path.write_text(brief)
    print(f"[generate-brief] ✓ Brief written to {brief_path}")
    print(f"[generate-brief]   {len(brief.splitlines())} lines")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[generate-brief] ERROR: {e}", file=sys.stderr)
        sys.exit(1)
