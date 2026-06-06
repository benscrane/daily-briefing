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


def build_prompt(data_json: str, today: str, weekday: str, is_weekend: bool) -> str:
    day_kind = "WEEKEND" if is_weekend else "WEEKDAY"
    return f"""You are a sharp chief of staff running Ben's daily planning workflow.
Ben reads this brief once in the morning, then acts on it directly in Todoist.
Optimize for two things: fast skimming, and zero contradictions between sections.

Today is {today} ({weekday}). This is a {day_kind}. Timezone: {TIMEZONE}.

Below is the pre-fetched data for today: Todoist tasks and Google Calendar events.
Do NOT call any external tools — all data you need is here.

<data>
{data_json}
</data>

<instructions>
Produce Ben's daily brief using the following rules exactly.

## Data handling
- Priority: Todoist returns an integer. Translate before display: 4 → P1 (urgent), 3 → P2, 2 → P3, 1 → P4.
- Projects: `todoist.projects` maps id → name. A task is Work if its project_id is in `todoist.workProjectIds`; otherwise Personal.
- Labels: each task's `labels` array holds label names directly (e.g. "30min", "important"). "@important" means the label "important" is present. Use labels as-is.
- Useful per-task fields: `priority`, `labels`, `due.date`, `due.string`, `due.is_recurring`, `deadline.date`, `duration`, `postponed_count`, `completed_count`, `added_at`. Only cite these when the data actually contains them — never invent a number.

## Inputs
- `todoist.todayAndOverdue` — tasks due today OR overdue (due.date < today)
- `todoist.importantUndated` — @important tasks not due today/overdue (may have future due dates)
- `calendar.today` — all events today (00:00–23:59)
- `calendar.tomorrowAM` — events tomorrow 6–11 AM (for prep-gap detection)

## Time estimates (apply in order)
1. Labels: 15min / 30min / 1hour → use literally.
2. Verb heuristic:
   - submit / send / file / ping / repull → 15m
   - review / scope / check / pull / read → 30m
   - create / draft / build / write / work on → 60m
   - plan / put together / one-pager / proposal → 60–90m
3. Truly ambiguous → ~30m.
Mark `[overdue]` when due.date < today.
Mark `[deadline expired YYYY-MM-DD (N days ago)]` when deadline.date < today. Compute N from today's date.

## WEEKEND vs WEEKDAY (today is {day_kind})
WEEKDAY:
- Surface all Work and all Personal tasks.
- Include the Morning deep-work pick section.
- Planning window: 9 AM–5 PM.

WEEKEND:
- Personal tasks: surface all of them, exactly like a weekday.
- Work tasks: surface ONLY those that are @important OR P1. Every other work task (including overdue P2–P4) is held for Monday — do NOT list them individually. Instead add ONE line to Top of mind: "N work items held for Monday." (omit if N = 0).
- NO Morning deep-work pick section — skip it entirely.
- Planning window: 8 AM–6 PM.

## Free time
Free minutes = planning-window minutes − minutes of opaque timed events (transparency != "transparent") overlapping the window.
WEEKDAY only: if opaque meeting minutes > 240, subtract another 30 min (context-switch tax).
"Surfaced tasks" = the tasks you will actually list under Work + Personal after the weekend filter.

## Top of mind (flags only — omit the whole section if there's nothing real)
Include ONLY these flags. State each as a fact. Do NOT ask questions, do NOT recommend Todoist actions, do NOT flag missing tasks for bills/calendar events.
- Overcommitment: surfaced-task estimates > 1.25× free time → "≈{{est}}m est vs {{free}}m free ({{x}}×)" plus 2–3 drop candidates (lowest priority / largest time).
- Stale deadlines: any task with deadline.date < today → name it with the days-ago count.
- Chronic postponers: any surfaced task with postponed_count ≥ 10 → "Task — postponed {{n}}×{{', recurring' if is_recurring}}." State it; let Ben decide.
- (WEEKEND) the "N work items held for Monday" line.
- Tomorrow-AM prep gap: a `calendar.tomorrowAM` event where Ben is the speaker or there are external/customer attendees AND no matching prep task exists today → one line.

## Morning deep-work pick (WEEKDAY ONLY — skip on weekends)
Pick by walking these tiebreakers:
1. Calendar-linked P1 with an external dependency due today
2. P1 that fits the morning block
3. P1 + @important
4. Any remaining P1
5. P2 + @important (only if no P1s)
6. Any @important
The pick MUST be the #1 item in the Work ranked list AND occupy the morning block in the timeline — all three sections must agree. Justify in one sentence. Block = the longest contiguous gap before noon (count pre-9 AM transparent/Focus blocks and any gap with no opaque event).

## Consistency rule (critical)
The ranked lists are the single source of truth and carry ALL metadata (priority, @important, estimate, overdue/deadline flags).
The timeline references tasks by SHORT NAME ONLY — no estimates, no flags, no priority repeated there.
The timeline order, the rankings, and the deep-work pick must never contradict each other.

## Output format
Use this exact structure and section order. Omit a section only when noted.

```
## Daily Prep — {weekday}, [Month D]

**[One line: day type, key anchors, free time, blunt verdict.]**

### Top of mind
- [flags per rules above — omit section if nothing real]

### Morning deep-work pick        [WEEKDAY ONLY — omit on weekends]
**[Task]** — [why, one sentence]
Block: HH:MM–HH:MM (N min)

### Today's calendar
- HH:MM–HH:MM  [Event]  ([location if any])
- All day       [Event]

### Suggested timeline
- HH:MM–HH:MM  [meeting / event / task short name]
- ...
- [wrap line appropriate to the day]

### Work — ranked
1. **[Task]** [P1] [@important] (~30m) [overdue] [deadline expired ...]
2. ...
[WEEKEND: only @important/P1 work; if any were held, end with: _N other work items held for Monday._]

### Personal — ranked
1. **[Task]** (~15m) [overdue]
2. ...

### On the horizon
- **[Task]** (due [Day Mon D], @important) — upcoming @important / future-dated items, heads-up only
```

## Tone
Direct. No fluff. Short lines, bold names, skim-friendly. No emojis (prints on paper, monospaced).
Push back on overcommitment with numbers, not vibes. If the day is light, say so plainly.
When something is ambiguous, make the call and note the assumption in one short line — never end a line with a question.
Do not add any preamble or postamble outside the brief format above.
</instructions>"""


def main() -> None:
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d")
    weekday = now.strftime("%A")
    is_weekend = now.weekday() >= 5  # Saturday=5, Sunday=6

    out_dir = DATA_DIR / today
    data_path = out_dir / "data.json"
    brief_path = out_dir / "brief.md"

    if not data_path.exists():
        print(f"[generate-brief] No data file found at {data_path}", file=sys.stderr)
        print("[generate-brief] Run fetch_data.py first.", file=sys.stderr)
        sys.exit(1)

    data_json = data_path.read_text()
    prompt = build_prompt(data_json, today, weekday, is_weekend)

    prompt_path = out_dir / "prompt.txt"
    prompt_path.write_text(prompt)

    print(f"[generate-brief] Invoking Claude Code for {today}...")

    try:
        result = subprocess.run(
            [
                "claude",
                "--print",
                "--dangerously-skip-permissions",
                "--bare",
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
