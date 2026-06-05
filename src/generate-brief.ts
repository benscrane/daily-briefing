/**
 * generate-brief.ts
 *
 * Reads today's data.json, builds a prompt embedding the full daily-prep
 * skill logic, then invokes `claude` CLI (Claude Code) in --print mode
 * to generate the brief. Output is written to DATA_DIR/YYYY-MM-DD/brief.md
 *
 * Claude Code CLI flags used:
 *   --print                       non-interactive, print response to stdout then exit
 *   --dangerously-skip-permissions  suppress permission prompts for automation
 *   -p "<prompt>"                 the prompt to run
 */

import * as fs from "fs";
import * as path from "path";
import { spawnSync } from "child_process";
import * as dotenv from "dotenv";

dotenv.config({ path: path.resolve(__dirname, "../.env") });

const DATA_DIR = process.env.DATA_DIR || path.resolve(__dirname, "../brief_output");
const TIMEZONE = process.env.TIMEZONE || "America/Chicago";

function toLocalDateString(date: Date, tz: string): string {
  return date.toLocaleDateString("en-CA", { timeZone: tz });
}

function buildPrompt(dataJson: string, today: string): string {
  // Embed the raw data JSON directly in the prompt. Claude Code will
  // reason over it without needing MCP tool calls — the data is already
  // fetched by fetch-data.ts.
  return `You are a sharp chief of staff running Ben's daily planning workflow.

Today's date is ${today}. Timezone: ${TIMEZONE}.

Below is the pre-fetched data for today: Todoist tasks and Google Calendar events.
Do NOT call any external tools — all data you need is here.

<data>
${dataJson}
</data>

<instructions>
Produce Ben's daily brief using the following rules exactly.

## Priority mapping
Todoist's API returns priority as an integer where 4=P1 (urgent), 3=P2, 2=P3, 1=normal/P4.
Always translate before display: API priority 4 → P1, 3 → P2, 2 → P3, 1 → P4.

## Projects
The \`todoist.projects\` map gives project id → name. Match each task's project_id to get its name.
Tasks in the project named "Redox" are Work. Everything else is Personal.

## Labels
Each task's \`labels\` array contains label names directly (e.g. "30min", "important"). Use them as-is.

## Step 1: Understand the data
- \`todoist.todayAndOverdue\` — tasks due today OR overdue (due_date < today)
- \`todoist.importantUndated\` — @important tasks not due today/overdue (may have future due dates)
- \`calendar.today\` — all events today (00:00–23:59)
- \`calendar.tomorrowAM\` — events tomorrow 6 AM–11 AM (for prep-gap detection)

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

\`\`\`
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
\`\`\`

## Tone
Direct. No fluff. Short lines, bold names, skim-friendly.
Push back on overcommitment with numbers, not vibes.
If the day is light, say so.
No emojis anywhere. This prints on paper in a monospaced font.

Do not add any preamble or postamble outside the brief format above.
</instructions>`;
}

async function main() {
  const now = new Date();
  const today = toLocalDateString(now, TIMEZONE);
  const dir = path.join(DATA_DIR, today);
  const dataPath = path.join(dir, "data.json");
  const briefPath = path.join(dir, "brief.md");

  if (!fs.existsSync(dataPath)) {
    console.error(`[generate-brief] No data file found at ${dataPath}`);
    console.error(`[generate-brief] Run fetch-data.ts first.`);
    process.exit(1);
  }

  const dataJson = fs.readFileSync(dataPath, "utf8");
  const prompt = buildPrompt(dataJson, today);

  // Write prompt for debugging
  const promptPath = path.join(dir, "prompt.txt");
  fs.writeFileSync(promptPath, prompt);

  console.log(`[generate-brief] Invoking Claude Code for ${today}...`);

  const result = spawnSync(
    "claude",
    ["--print", "--dangerously-skip-permissions", "--model", "claude-sonnet-4-6", "-p", prompt],
    {
      encoding: "utf8",
      timeout: 300_000, // 5 minutes
      maxBuffer: 10 * 1024 * 1024,
      stdio: ["ignore", "pipe", "pipe"],
    }
  );

  if (result.status !== 0 || result.error) {
    console.error("[generate-brief] Claude Code failed:");
    console.error("  exit code:", result.status);
    console.error("  signal:", result.signal);
    console.error("  error:", result.error?.message);
    console.error("  stderr:", result.stderr || "(empty)");
    console.error("  stdout:", result.stdout?.slice(0, 500) || "(empty)");
    process.exit(1);
  }

  let brief: string = result.stdout;

  // Clean any residual ANSI codes just in case
  brief = brief.replace(/\x1B\[[0-9;]*[mGKHF]/g, "").trim();

  fs.writeFileSync(briefPath, brief);
  console.log(`[generate-brief] ✓ Brief written to ${briefPath}`);
  console.log(`[generate-brief]   ${brief.split("\n").length} lines`);
}

main().catch((err) => {
  console.error("[generate-brief] ERROR:", err.message);
  process.exit(1);
});