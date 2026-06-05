/**
 * fetch-data.ts
 *
 * Pulls today's Todoist tasks (including overdue) and Google Calendar events
 * (today + tomorrow AM) then writes a dated JSON file to DATA_DIR.
 *
 * Output: DATA_DIR/YYYY-MM-DD/data.json
 */

import * as fs from "fs";
import * as path from "path";
import axios from "axios";
import { google } from "googleapis";
import * as dotenv from "dotenv";

dotenv.config({ path: path.resolve(__dirname, "../.env") });

// ─── Config ──────────────────────────────────────────────────────────────────

const TODOIST_TOKEN = process.env.TODOIST_API_TOKEN!;
const GOOGLE_CLIENT_ID = process.env.GOOGLE_CLIENT_ID!;
const GOOGLE_CLIENT_SECRET = process.env.GOOGLE_CLIENT_SECRET!;
const GOOGLE_REFRESH_TOKEN = process.env.GOOGLE_REFRESH_TOKEN!;
const CALENDAR_ID = process.env.GOOGLE_CALENDAR_ID ?? "primary";
const DATA_DIR = process.env.DATA_DIR ?? path.resolve(__dirname, "../data");
const TIMEZONE = process.env.TIMEZONE ?? "America/Chicago";

function required(name: string, val: string | undefined): string {
  if (!val) throw new Error(`Missing env var: ${name}`);
  return val;
}

// ─── Date helpers ─────────────────────────────────────────────────────────────

function toLocalDateString(date: Date, tz: string): string {
  return date.toLocaleDateString("en-CA", { timeZone: tz }); // YYYY-MM-DD
}

function startOfDayUTC(dateStr: string, tz: string): string {
  // Returns ISO string for midnight local time in tz
  const d = new Date(`${dateStr}T00:00:00`);
  // Construct as local midnight via Intl
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: tz,
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
    hour12: false,
  });
  // Use a simpler approach: just pass the string with timezone offset
  return `${dateStr}T00:00:00`;
}

// ─── Todoist ──────────────────────────────────────────────────────────────────

interface TodoistTask {
  id: string;
  content: string;
  description: string;
  project_id: string;
  section_id: string | null;
  parent_id: string | null;
  priority: number; // 1=normal, 2=p3, 3=p2, 4=p1 in Todoist's inverted scale
  due: { string: string; date: string; is_recurring: boolean; datetime?: string } | null;
  deadline: { date: string; lang: string } | null;
  labels: string[];
  is_completed: boolean;
  created_at: string;
  url: string;
}

async function fetchTodoistTasks(today: string): Promise<{
  todayAndOverdue: TodoistTask[];
  important: TodoistTask[];
  projects: Record<string, string>; // id → name
}> {
  const api = axios.create({
    baseURL: "https://api.todoist.com/rest/v2",
    headers: { Authorization: `Bearer ${TODOIST_TOKEN}` },
  });

  // Fetch projects for name lookup
  const projectsRes = await api.get<Array<{ id: string; name: string }>>("/projects");
  const projects: Record<string, string> = {};
  for (const p of projectsRes.data) {
    projects[p.id] = p.name;
  }

  // Today's tasks + overdue: filter = "today | overdue"
  const todayRes = await api.get<TodoistTask[]>("/tasks", {
    params: { filter: "today | overdue" },
  });

  // @important label tasks (any date)
  const importantRes = await api.get<TodoistTask[]>("/tasks", {
    params: { filter: "@important" },
  });

  // Deduplicate: important tasks already in today/overdue shouldn't double-count
  const todayIds = new Set(todayRes.data.map((t) => t.id));
  const importantOnly = importantRes.data.filter((t) => !todayIds.has(t.id));

  return {
    todayAndOverdue: todayRes.data,
    important: importantOnly,
    projects,
  };
}

// ─── Google Calendar ──────────────────────────────────────────────────────────

interface CalendarEvent {
  id: string;
  summary: string;
  description?: string;
  location?: string;
  start: { dateTime?: string; date?: string; timeZone?: string };
  end: { dateTime?: string; date?: string; timeZone?: string };
  attendees?: Array<{ email: string; displayName?: string; responseStatus: string; self?: boolean }>;
  status: string;
  transparency?: string; // "transparent" = free/focus block
  organizer?: { email: string; displayName?: string; self?: boolean };
  htmlLink: string;
}

async function fetchCalendarEvents(today: string, tomorrow: string): Promise<{
  todayEvents: CalendarEvent[];
  tomorrowAMEvents: CalendarEvent[];
}> {
  const oAuth2Client = new google.auth.OAuth2(
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET
  );
  oAuth2Client.setCredentials({ refresh_token: GOOGLE_REFRESH_TOKEN });

  const calendar = google.calendar({ version: "v3", auth: oAuth2Client });

  // Today: full day
  const todayStart = new Date(`${today}T00:00:00`);
  const todayEnd = new Date(`${today}T23:59:59`);

  // Tomorrow: 6 AM – 11 AM (for prep-gap detection)
  const tomorrowStart = new Date(`${tomorrow}T06:00:00`);
  const tomorrowEnd = new Date(`${tomorrow}T11:00:00`);

  // Convert to UTC-aware ISO strings using Intl
  function toUTCIso(localDate: Date, tz: string): string {
    // Intl trick: format in target tz, parse back to get offset
    const utcMs = localDate.getTime();
    const tzOffsetMs = getTimezoneOffset(localDate, tz);
    return new Date(utcMs - tzOffsetMs).toISOString();
  }

  function getTimezoneOffset(date: Date, tz: string): number {
    const utcStr = date.toLocaleString("en-US", { timeZone: "UTC" });
    const tzStr = date.toLocaleString("en-US", { timeZone: tz });
    return new Date(utcStr).getTime() - new Date(tzStr).getTime();
  }

  const [todayRes, tomorrowRes] = await Promise.all([
    calendar.events.list({
      calendarId: CALENDAR_ID,
      timeMin: toUTCIso(todayStart, TIMEZONE),
      timeMax: toUTCIso(todayEnd, TIMEZONE),
      singleEvents: true,
      orderBy: "startTime",
      maxResults: 50,
    }),
    calendar.events.list({
      calendarId: CALENDAR_ID,
      timeMin: toUTCIso(tomorrowStart, TIMEZONE),
      timeMax: toUTCIso(tomorrowEnd, TIMEZONE),
      singleEvents: true,
      orderBy: "startTime",
      maxResults: 20,
    }),
  ]);

  return {
    todayEvents: (todayRes.data.items ?? []) as CalendarEvent[],
    tomorrowAMEvents: (tomorrowRes.data.items ?? []) as CalendarEvent[],
  };
}

// ─── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  required("TODOIST_API_TOKEN", TODOIST_TOKEN);
  required("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID);
  required("GOOGLE_CLIENT_SECRET", GOOGLE_CLIENT_SECRET);
  required("GOOGLE_REFRESH_TOKEN", GOOGLE_REFRESH_TOKEN);

  const now = new Date();
  const today = toLocalDateString(now, TIMEZONE);
  const tomorrowDate = new Date(now);
  tomorrowDate.setDate(tomorrowDate.getDate() + 1);
  const tomorrow = toLocalDateString(tomorrowDate, TIMEZONE);

  console.log(`[fetch-data] Fetching data for ${today} (tz: ${TIMEZONE})`);

  const [todoistData, calendarData] = await Promise.all([
    fetchTodoistTasks(today),
    fetchCalendarEvents(today, tomorrow),
  ]);

  const output = {
    generatedAt: now.toISOString(),
    date: today,
    timezone: TIMEZONE,
    todoist: {
      todayAndOverdue: todoistData.todayAndOverdue,
      importantUndated: todoistData.important,
      projects: todoistData.projects,
    },
    calendar: {
      today: calendarData.todayEvents,
      tomorrowAM: calendarData.tomorrowAMEvents,
    },
  };

  // Write to dated directory
  const dir = path.join(DATA_DIR, today);
  fs.mkdirSync(dir, { recursive: true });
  const outPath = path.join(dir, "data.json");
  fs.writeFileSync(outPath, JSON.stringify(output, null, 2));

  console.log(`[fetch-data] ✓ Wrote ${outPath}`);
  console.log(
    `[fetch-data]   ${todoistData.todayAndOverdue.length} tasks today/overdue, ` +
    `${todoistData.important.length} @important undated, ` +
    `${calendarData.todayEvents.length} events today, ` +
    `${calendarData.tomorrowAMEvents.length} events tomorrow AM`
  );
}

main().catch((err) => {
  console.error("[fetch-data] ERROR:", err.message);
  process.exit(1);
});