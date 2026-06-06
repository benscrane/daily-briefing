#!/usr/bin/env python3
"""
generate_brief.py

Reads today's data.json, builds a prompt, then invokes the `claude` CLI
in --print mode to generate the brief.

Output: DATA_DIR/YYYY-MM-DD/brief.md
"""

import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent / "brief_output"))
TIMEZONE = os.environ.get("TIMEZONE", "America/Chicago")


def build_prompt(data_json: str, today: str) -> str:
    return f"""You are a sharp chief of staff running Ben's daily planning workflow.

Today's date is {today}. Timezone: {TIMEZONE}.

Below is the pre-fetched data for today: Todoist tasks and Google Calendar events.
Do NOT call any external tools — all data you need is here.

<data>
{data_json}
</data>

<instructions>
Produce Ben's daily brief using the following rules exactly.

## Priority mapping
Todoist's API returns priority as an integer where 4=P1 (urgent), 3=P2, 2=P3, 1=normal/P4.
Always translate before display: API priority 4 → P1, 3 → P2, 2 → P3, 1 → P4.

## Projects
The `todoist.projects` map gives project id → name. Match each task's project_id to get its name.
Tasks in the project named "Redox" are Work. Everything else is Personal.

## Labels
Each task's `labels` array contains label names directly (e.g. "30min", "important"). Use them as-is.

## Step 1: Understand the data
- `todoist.todayAndOverdue` — tasks due today OR overdue (due_date < today)
- `todoist.importantUndated` — @important tasks not due today/overdue (may have future due dates)
- `calendar.today` — all events today (00:00–23:59)
- `calendar.tomorrowAM` — events tomorrow 6 AM–11 AM (for prep-gap detection)

## Step 2: Bucket and estimate
Work = Redox project. Personal = everything else.

Time estimates — apply in order:
1. Labels: 15min / 30min / 1hour → use literally
2. Heuristic by verb:
   - submit / send / file / ping / repull → 15m
   - review / scope / check / pull / read → 30m
   - create / draft / build / write / work on → 60m
   - plan / put together / one-pager / proposal → 60–90m
3. Truly ambiguous → 30m, flagged as ~30m?

Overdue = due.date < today → mark [overdue]
Stale deadline = deadline.date < today → mark [deadline expired DATE]

## Step 3: Compute the day
Working window: 9 AM–5 PM Central = 480 min.
Meeting minutes = sum duration of opaque calendar events (transparency != "transparent") overlapping 9–5.
Free minutes = 480 − meeting minutes.
If meeting minutes > 240, subtract another 30 min (context-switch tax).

Deep-work block: longest contiguous gap between 6 AM and noon, counting:
- Pre-9 AM transparent/self-scheduled blocks (Focus Time, etc.)
- 9 AM onward gaps with no opaque event

## Step 4: Surface flags
- Overcommitment: estimates > 1.25× free time → flag with numbers + drop list
- Calendar/Todoist drift: for each all-day event, check if a task matches by shared proper nouns/acronyms
- Stale deadlines
- Tomorrow-AM prep gaps: external attendees, customer names, agenda gaps + Ben is speaker
- Personal anchors: timed personal events (school pickup, appointments)

## Step 5: Pick morning deep-work item
Walk tiebreakers:
1. Calendar-linked P1 with external dependency due today
2. P1 that fits the block size
3. P1 + @important
4. Any remaining P1
5. P2 + @important (only if no P1s)
6. Any @important
Justify in one sentence.

## Step 6: Output format
Use this exact structure:

```
## Daily Prep — [Day, Date]

**[One-line: meeting load, free time, verdict.]**

### Top of mind
- [flags — omit section only if everything is clean]

### Morning deep-work pick
**[Task]** — [why, one sentence]
Block: [HH:MM–HH:MM] ([N] min)

### Work — ranked
1. **[Task]** [P1] [@important] (~30m) [overdue|deadline expired if applicable]
2. ...

### Personal — ranked
1. **[Task]** (~15m)
2. ...

### Today's calendar
- HH:MM–HH:MM  [Event]  [flags]
- ...

### Suggested timeline
- HH:MM–HH:MM  Deep work: [pick]
- HH:MM–HH:MM  [Meeting or Task]
- ...
- 5:00  Wrap

### Undated @important (not slotted)
- [Task] — slot today? (y/n)
```

## Tone
Direct. No fluff. Short lines, bold names, skim-friendly.
Push back on overcommitment with numbers, not vibes.
If the day is light, say so.
No emojis anywhere. This prints on paper in a monospaced font.

Do not add any preamble or postamble outside the brief format above.
</instructions>"""


def main() -> None:
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d")

    out_dir = DATA_DIR / today
    data_path = out_dir / "data.json"
    brief_path = out_dir / "brief.md"

    if not data_path.exists():
        print(f"[generate-brief] No data file found at {data_path}", file=sys.stderr)
        print("[generate-brief] Run fetch_data.py first.", file=sys.stderr)
        sys.exit(1)

    data_json = data_path.read_text()
    prompt = build_prompt(data_json, today)

    prompt_path = out_dir / "prompt.txt"
    prompt_path.write_text(prompt)

    print(f"[generate-brief] Invoking Claude Code for {today}...")

    try:
        result = subprocess.run(
            [
                "claude",
                "--print",
                "--dangerously-skip-permissions",
                "--model",
                "claude-sonnet-4-6",
                "-p",
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        print("[generate-brief] ERROR: Claude Code timed out after 5 minutes.", file=sys.stderr)
        sys.exit(1)

    if result.returncode != 0:
        print("[generate-brief] Claude Code failed:", file=sys.stderr)
        print(f"  exit code: {result.returncode}", file=sys.stderr)
        print(f"  stderr: {result.stderr[:500] if result.stderr else '(empty)'}", file=sys.stderr)
        print(
            f"  stdout: {result.stdout[:500] if result.stdout else '(empty)'}",
            file=sys.stderr,
        )
        sys.exit(1)

    brief = re.sub(r"\x1B\[[0-9;]*[mGKHF]", "", result.stdout).strip()

    brief_path.write_text(brief)
    print(f"[generate-brief] ✓ Brief written to {brief_path}")
    print(f"[generate-brief]   {len(brief.splitlines())} lines")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[generate-brief] ERROR: {e}", file=sys.stderr)
        sys.exit(1)
