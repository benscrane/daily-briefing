import { google } from "googleapis";
import * as dotenv from "dotenv";
import * as path from "path";

dotenv.config({ path: path.resolve(__dirname, "../.env") });

async function main() {
  const auth = new google.auth.OAuth2(
    process.env.GOOGLE_CLIENT_ID,
    process.env.GOOGLE_CLIENT_SECRET
  );
  auth.setCredentials({ refresh_token: process.env.GOOGLE_REFRESH_TOKEN });

  const cal = google.calendar({ version: "v3", auth });
  const res = await cal.calendarList.list();

  for (const c of res.data.items ?? []) {
    console.log(`${c.summary?.padEnd(40)} ${c.id}`);
  }
}

main().catch((err) => { console.error(err.message); process.exit(1); });
