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
const DATA_DIR = process.env.DATA_DIR || path.resolve(__dirname, "../brief_output");
const TIMEZONE = process.env.TIMEZONE || "America/Chicago";

const CONFIG_PATH = path.resolve(__dirname, "../config.json");
const config = JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8"));
const CALENDAR_IDS: string[] = config.calendarIds ?? ["primary"];

function required(name: string, val: string | undefined): string {
  if (!val) throw new Error(`Missing env var: ${name}`);
  return val;
}

// ─── Date helpers ─────────────────────────────────────────────────────────────

function toLocalDateString(date: Date, tz: string): string {
  return date.toLocaleDateString("en-CA", { timeZone: tz }); // YYYY-MM-DD
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
  labels: string[]; // label IDs in API v1
  checked: boolean;
  added_at: string;
}

interface TodoistPagedResponse<T> {
  results: T[];
  next_cursor: string | null;
}

async function fetchTodoistTasks(today: string): Promise<{
  todayAndOverdue: TodoistTask[];
  important: TodoistTask[];
  projects: Record<string, string>; // id → name
  labels: Record<string, string>;   // id → name
}> {
  const api = axios.create({
    baseURL: "https://api.todoist.com/api/v1/",
    headers: { Authorization: `Bearer ${TODOIST_TOKEN}` },
  });

  // Fetch projects and labels for name lookup
  const [projectsRes, labelsRes] = await Promise.all([
    api.get<TodoistPagedResponse<{ id: string; name: string }>>("projects", { params: { limit: 200 } }),
    api.get<TodoistPagedResponse<{ id: string; name: string }>>("labels", { params: { limit: 200 } }),
  ]);

  const projects: Record<string, string> = {};
  for (const p of projectsRes.data.results) {
    projects[p.id] = p.name;
  }

  const labels: Record<string, string> = {};
  for (const l of labelsRes.data.results) {
    labels[l.id] = l.name;
  }

  // Today's tasks + overdue
  const todayRes = await api.get<TodoistPagedResponse<TodoistTask>>("tasks/filter", {
    params: { query: "today | overdue", limit: 200 },
  });

  // @important label tasks (any date)
  const importantRes = await api.get<TodoistPagedResponse<TodoistTask>>("tasks/filter", {
    params: { query: "@important", limit: 200 },
  });

  // Deduplicate: important tasks already in today/overdue shouldn't double-count
  const todayIds = new Set(todayRes.data.results.map((t) => t.id));
  const importantOnly = importantRes.data.results.filter((t) => !todayIds.has(t.id));

  return {
    todayAndOverdue: todayRes.data.results,
    important: importantOnly,
    projects,
    labels,
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

  const results = await Promise.all(
    CALENDAR_IDS.flatMap((calendarId) => [
      calendar.events.list({
        calendarId,
        timeMin: todayStart.toISOString(),
        timeMax: todayEnd.toISOString(),
        singleEvents: true,
        orderBy: "startTime",
        maxResults: 50,
      }),
      calendar.events.list({
        calendarId,
        timeMin: tomorrowStart.toISOString(),
        timeMax: tomorrowEnd.toISOString(),
        singleEvents: true,
        orderBy: "startTime",
        maxResults: 20,
      }),
    ])
  );

  const todayEvents: CalendarEvent[] = [];
  const tomorrowAMEvents: CalendarEvent[] = [];

  for (let i = 0; i < results.length; i += 2) {
    todayEvents.push(...((results[i].data.items ?? []) as CalendarEvent[]));
    tomorrowAMEvents.push(...((results[i + 1].data.items ?? []) as CalendarEvent[]));
  }

  // Sort merged results by start time
  const startTime = (e: CalendarEvent) => e.start.dateTime ?? e.start.date ?? "";
  todayEvents.sort((a, b) => startTime(a).localeCompare(startTime(b)));
  tomorrowAMEvents.sort((a, b) => startTime(a).localeCompare(startTime(b)));

  return { todayEvents, tomorrowAMEvents };
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
      labels: todoistData.labels,
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
  if (err.response) {
    console.error("  status:", err.response.status);
    console.error("  url:", err.config?.url);
    console.error("  baseURL:", err.config?.baseURL);
  }
  process.exit(1);
});