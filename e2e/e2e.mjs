// Real-browser E2E: two users with fake camera/mic devices, live local LiveKit, and mock AI provider.
//
//   1. start the API:       cd backend && PROVIDER=mock uvicorn app.main:get_app --factory --port 8000
//   2. start the frontend:  cd frontend && npm run build && npm start
//   3. run this:            cd e2e && npm i && npx playwright install chromium && node e2e.mjs
//
// Without a LiveKit server the video pane shows "disconnected" (expected); this test covers the
// lobby, pre-join, translation WebSocket, captions, people/host UI and responsive layout.
// Set CHROME_PATH to use a specific Chrome/Chromium binary. Screenshots go to ./shots.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium as pw } from "playwright";

const BASE = process.env.BASE_URL || "http://localhost:3000";
const API = process.env.API_URL || "http://localhost:8000";
fs.mkdirSync("shots", { recursive: true });

// 16 kHz mono PCM16 wav: 1.2 s tone bursts separated by 1.5 s silence (what the VAD treats as "speech").
function makeSpeechWav() {
  const sr = 16000, parts = [];
  const sil = (ms) => new Int16Array((sr * ms) / 1000);
  const tone = (ms) => Int16Array.from({ length: (sr * ms) / 1000 }, (_, i) => Math.round(8000 * Math.sin((2 * Math.PI * 220 * i) / sr)));
  for (let i = 0; i < 8; i++) parts.push(sil(300), tone(1200), sil(1500));
  const total = parts.reduce((n, p) => n + p.length, 0);
  const buf = Buffer.alloc(44 + total * 2);
  buf.write("RIFF", 0); buf.writeUInt32LE(36 + total * 2, 4); buf.write("WAVEfmt ", 8);
  buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20); buf.writeUInt16LE(1, 22);
  buf.writeUInt32LE(sr, 24); buf.writeUInt32LE(sr * 2, 28); buf.writeUInt16LE(2, 32); buf.writeUInt16LE(16, 34);
  buf.write("data", 36); buf.writeUInt32LE(total * 2, 40);
  let off = 44;
  for (const p of parts) for (const v of p) { buf.writeInt16LE(v, off); off += 2; }
  const f = path.join(os.tmpdir(), "lingua_fake_speech.wav");
  fs.writeFileSync(f, buf);
  return f;
}

const wav = makeSpeechWav();
const browser = await pw.launch({
  headless: true,
  executablePath: process.env.CHROME_PATH || undefined,
  args: ["--no-sandbox", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
         `--use-file-for-fake-audio-capture=${wav}`, "--autoplay-policy=no-user-gesture-required"],
});
const results = [];
const check = (name, ok, extra = "") => { results.push([name, ok, extra]); console.log(ok ? "PASS" : "FAIL", name, extra); };

async function newUser(label) {
  const ctx = await browser.newContext({ permissions: ["microphone", "camera"], viewport: { width: 1366, height: 820 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text().slice(0, 160)); });
  return { label, ctx, page, errors };
}

const A = await newUser("Rahul"), B = await newUser("Emma");

// ---------- lobby ----------
await A.page.goto(BASE);
await A.page.waitForSelector("text=Start a new meeting");
await A.page.screenshot({ path: "shots/1-lobby.png" });
check("lobby renders", true);

await A.page.fill('input[placeholder="e.g. Satyam"]', "Rahul");
await A.page.locator("select").nth(0).selectOption("hi-en");
await A.page.locator("select").nth(1).selectOption("hi");
await A.page.click("text=Start a new meeting");
await A.page.waitForURL(/\/room\//);
const code = decodeURIComponent(A.page.url().split("/room/")[1]);
check("room code generated", /^[a-z0-9]{3}-[a-z0-9]{4}-[a-z0-9]{3}$/.test(code), code);

// ---------- pre-join ----------
await A.page.waitForSelector("text=Ready to join?");
await A.page.waitForTimeout(1500);
await A.page.screenshot({ path: "shots/2-prejoin.png" });
const camCount = await A.page.locator("select").nth(3).locator("option").count();
// Chromium may expose only the browser-default fake camera option. The later media checks
// verify that both participants publish decoded video frames, which is the actual requirement.
check("prejoin exposes a camera device option", camCount >= 1, `options=${camCount}`);
const meterWidth = await A.page.locator(".meter > div").evaluate((el) => el.style.width).catch(() => "");
check("prejoin mic meter present", meterWidth !== "", `width=${meterWidth}`);
await A.page.click("text=Join now");
await A.page.waitForSelector(".meeting", { timeout: 15000 });
check("A entered meeting room", true);

// ---------- second user via invite link ----------
await B.page.goto(`${BASE}/?room=${code}`);
const prefilled = await B.page.inputValue('input[placeholder="abc-defg-hij"]');
check("invite link prefills room code", prefilled === code, prefilled);
await B.page.fill('input[placeholder="e.g. Satyam"]', "Emma");
await B.page.locator("select").nth(0).selectOption("en");
await B.page.locator("select").nth(1).selectOption("en");
await B.page.click("text=Join meeting");
await B.page.waitForSelector("text=Ready to join?");
await B.page.waitForTimeout(800);
await B.page.click("text=Join now");
await B.page.waitForSelector(".meeting", { timeout: 15000 });
check("B entered meeting room", true);
await B.page.getByText(/This browser cannot access a speech voice for English/).waitFor({ state: "visible", timeoutMs: 5000 });
check("headless browser explains unavailable English TTS accurately", true);

// ---------- translation, both directions ----------
const waitText = async (page, re, ms) => {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    const txt = await page.locator("body").innerText();
    if (re.test(txt)) return txt;
    await page.waitForTimeout(500);
  }
  return null;
};
const bTxt = await waitText(B.page, /\[English\] mock utterance/, 45000);
check("Emma receives English translation of Rahul's speech", !!bTxt);
const aTxt = await waitText(A.page, /\[Hindi\] mock utterance/, 45000);
check("Rahul receives Hindi translation of Emma's speech", !!aTxt);

const aPill = await A.page.locator(".pill", { hasText: "Translation" }).first().innerText();
check("translation connection pill says open", /open/.test(aPill), aPill);

// invite button + settings tab
await A.page.click("text=Translation >> nth=-1").catch(() => {});
await A.page.screenshot({ path: "shots/3-meeting-A.png" });


// tabs render
await B.page.click("button.tab:has-text('Chat')");
check("chat tab renders input", await B.page.locator('input[aria-label="Chat message"]').isVisible());
await B.page.click("button.tab:has-text('People')");
const people = await B.page.locator(".person").allInnerTexts();
check("people list shows both users", people.length === 2, JSON.stringify(people));
check("first joiner is host (badge)", people.some((p) => /Rahul/.test(p) && /Host/.test(p)));
await B.page.screenshot({ path: "shots/5-people-B.png" });
await A.page.click("button.tab:has-text('People')");
const hostBtns = await A.page.locator(".host-bar button").allInnerTexts();
check("host sees Mute all / Lock controls", hostBtns.length === 2, JSON.stringify(hostBtns));
const guestHostBtns = await B.page.locator(".host-bar button").count();
check("guest does NOT see host controls", guestHostBtns === 0);
await A.page.screenshot({ path: "shots/6-people-A-host.png" });

// reactions popover + end-to-end reaction delivery over LiveKit
await B.page.click('button[aria-label="Reactions"]');
check("reaction picker opens with 6 emoji", (await B.page.locator(".emoji").count()) === 6);
await B.page.click('button[aria-label="React 👍"]');
await A.page.waitForSelector(".float", { timeout: 5000 });
check("reaction is delivered to the other participant", await A.page.locator(".float").count() > 0);

// Send a real-time chat message through LiveKit data channels.
await B.page.click("button.tab:has-text('Chat')");
const message = "LiveKit chat delivery check";
await B.page.locator('input[aria-label="Chat message"]').fill(message);
await B.page.click('button[type="submit"]');
await A.page.click("button.tab:has-text('Chat')");
await A.page.getByText(message).waitFor({ state: "visible", timeoutMs: 10000 });
check("chat message is delivered to the other participant", await A.page.getByText(message).isVisible());

// LiveKit media should publish real camera tracks to both participants.
const videoCount = await B.page.locator(".tile video").count();
const liveVideo = await B.page.locator(".tile video").evaluateAll((els) => els.map((v) => ({ ready: v.readyState, width: v.videoWidth, height: v.videoHeight })));
check("LiveKit video is connected", await B.page.locator("text=Video connected").count() > 0);
check("both local and remote camera tracks render", videoCount >= 2 && liveVideo.every((v) => v.ready >= 2 && v.width > 0 && v.height > 0), JSON.stringify(liveVideo));
const labels = await B.page.locator(".tile .label").allInnerTexts();
check("video tiles identify both participants", labels.some((x) => /Emma \(You\)/.test(x)) && labels.some((x) => /Rahul/.test(x)), JSON.stringify(labels));
await B.page.screenshot({ path: "shots/4-meeting-B.png" });

// mobile layout
await B.page.click('button[aria-label="Reactions"]');
await B.page.setViewportSize({ width: 390, height: 844 });
await B.page.waitForTimeout(400);
const pop = await B.page.locator(".react-pop").boundingBox();
check("emoji picker fully inside 390px viewport", !!pop && pop.x >= 0 && pop.x + pop.width <= 390, JSON.stringify(pop));
await B.page.screenshot({ path: "shots/7-mobile-B.png" });
const hOverflow = await B.page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2);
check("no horizontal overflow at 390px width", !hOverflow);

// Verify the host's server-side mute and remove actions against the live room.
await A.page.click("button.tab:has-text('People')");
const emmaRow = A.page.locator(".person", { hasText: "Emma" });
await emmaRow.getByRole("button", { name: "Mute", exact: true }).click();
await B.page.getByText("You were muted by the host.").waitFor({ state: "visible", timeoutMs: 10000 });
check("host can mute a remote participant", await B.page.getByText("You were muted by the host.").isVisible());
await emmaRow.getByRole("button", { name: "Remove", exact: true }).click();
await B.page.getByText("You were removed from this meeting by the host.").waitFor({ state: "visible", timeoutMs: 15000 });
check("host can remove a remote participant", await B.page.getByText("You were removed from this meeting by the host.").isVisible());

// server-side metrics
const m = await (await fetch(`${API}/api/metrics`)).json();
const e2e = m.stages.e2e_final_ms;
check("server recorded e2e latency samples", !!e2e && e2e.count >= 2, JSON.stringify(e2e));

console.log("\n--- browser console/page errors ---");
for (const u of [A, B]) { console.log(u.label, u.errors.length ? u.errors : "none"); }
await browser.close();
const failed = results.filter((r) => !r[1]).length;
console.log(`\n${results.length - failed}/${results.length} checks passed`);

process.exit(failed ? 1 : 0);
