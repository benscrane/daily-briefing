/**
 * setup-gcal-auth.ts
 *
 * Run ONCE on the Pi to authorize Google Calendar access and save
 * a refresh token to .env. After that, fetch-data.ts handles token
 * refresh automatically.
 *
 * Usage:
 *   npx ts-node setup-gcal-auth.ts
 */

import * as fs from "fs";
import * as http from "http";
import * as readline from "readline";
import { google } from "googleapis";
import * as dotenv from "dotenv";
import * as path from "path";

dotenv.config();

const SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"];
const ENV_PATH = path.resolve(__dirname, "../.env");

async function main() {
  const clientId = process.env.GOOGLE_CLIENT_ID;
  const clientSecret = process.env.GOOGLE_CLIENT_SECRET;

  if (!clientId || !clientSecret) {
    console.error("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env first.");
    process.exit(1);
  }

  const oAuth2Client = new google.auth.OAuth2(
    clientId,
    clientSecret,
    "http://localhost:3456/oauth2callback"
  );

  const authUrl = oAuth2Client.generateAuthUrl({
    access_type: "offline",
    scope: SCOPES,
    prompt: "consent", // force refresh token to be returned
  });

  console.log("\n─────────────────────────────────────────────────");
  console.log("1. Open this URL in your browser:\n");
  console.log(`   ${authUrl}`);
  console.log("\n2. Authorize, then paste the code shown below.");
  console.log("─────────────────────────────────────────────────\n");

  // Try local redirect server first; fall back to manual paste
  const code = await tryLocalServer().catch(() => askForCode());

  const { tokens } = await oAuth2Client.getToken(code);

  if (!tokens.refresh_token) {
    console.error(
      "\nNo refresh token returned. This happens if you've already authorized this app.\n" +
      "Go to https://myaccount.google.com/permissions, revoke access for this app, then re-run."
    );
    process.exit(1);
  }

  // Write refresh token into .env
  let envContent = fs.readFileSync(ENV_PATH, "utf8");
  if (envContent.includes("GOOGLE_REFRESH_TOKEN=")) {
    envContent = envContent.replace(
      /GOOGLE_REFRESH_TOKEN=.*/,
      `GOOGLE_REFRESH_TOKEN=${tokens.refresh_token}`
    );
  } else {
    envContent += `\nGOOGLE_REFRESH_TOKEN=${tokens.refresh_token}\n`;
  }
  fs.writeFileSync(ENV_PATH, envContent);

  console.log("\n✓ Refresh token saved to .env — you're all set.");
}

function tryLocalServer(): Promise<string> {
  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      const url = new URL(req.url!, "http://localhost:3456");
      const code = url.searchParams.get("code");
      if (code) {
        res.writeHead(200, { "Content-Type": "text/html" });
        res.end("<h1>Authorized ✓</h1><p>You can close this tab.</p>");
        server.close();
        resolve(code);
      } else {
        reject(new Error("No code in callback"));
      }
    });
    server.listen(3456);
    // Timeout after 5 minutes
    setTimeout(() => { server.close(); reject(new Error("Timeout")); }, 300_000);
  });
}

function askForCode(): Promise<string> {
  return new Promise((resolve) => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    rl.question("Paste the authorization code here: ", (code) => {
      rl.close();
      resolve(code.trim());
    });
  });
}

main().catch((err) => {
  console.error("Auth setup failed:", err.message);
  process.exit(1);
});