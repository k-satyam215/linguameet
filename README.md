# Windows quick start

From PowerShell at the project root, copy `.env.example` to `.env`. Start Docker Desktop and run `docker compose up -d livekit`. In separate terminals run the backend from `backend` with `uvicorn app.main:get_app --factory --host 127.0.0.1 --port 8000 --env-file ..\.env` and the frontend from `frontend` with `npm install` then `npm run dev`. Open `http://localhost:3000`.

The existing browser E2E suite uses mock AI and does not verify real LiveKit video or external-provider translation quality.

---

# LinguaMeet

Video meetings where each person speaks their own language and reads (and optionally hears) the meeting in theirs.
Focus: **low latency**, **Hinglish-aware** Hindi↔English, and multilingual-ready architecture.

## Free public deployment

The public version can use Vercel Hobby for the Next.js frontend, Render Free for the FastAPI/WebSocket API,
and LiveKit Cloud Build for video. These providers have independent free-tier limits and may change their terms.
Render sleeps an idle free API and its first request after sleep can take about a minute. The API keeps meeting
roster state in process memory, so an API restart temporarily interrupts translation and host controls; LiveKit
continues to carry media. LiveKit Cloud Build enforces a hard quota, so new sessions can stop working at the cap
without generating LiveKit overage charges. Vercel Hobby is for personal/non-commercial use.

1. Push this repository to GitHub **without `.env`** (the root `.gitignore` excludes it).
2. In Render, create a Blueprint from the repository and choose `render.yaml`. Add the LiveKit Cloud project
   WebSocket URL, API key, and API secret as Render environment values. `PROVIDER=auto` uses mock captions until
   `GROQ_API_KEY` is configured, then enables Groq speech recognition and translation. When enabled, spoken audio
   segments are sent to Groq for transcription and transcript text is sent to Groq for translation; review its
   current terms, privacy policy, and free-tier limits before adding a key.
3. In Vercel, import the repository and set the project Root Directory to `frontend`. Add
   `NEXT_PUBLIC_API_URL=https://<your-render-service>.onrender.com` before deploying.
4. In Render, set `CORS_ORIGINS` to the exact Vercel deployment origin (for example
   `https://linguameet-yourname.vercel.app`) and redeploy the API.
5. Test `/api/health`, then join the same room from two browsers with camera/microphone access. Use the resulting
   HTTPS site URL for invitations. Both users need a browser/OS voice for spoken translated playback; captions
   still work when a voice is unavailable.

Do not use the local LiveKit `devkey`/`secret` in a public deployment, and do not commit `.env` or paste API keys
into chat. Keep all provider credentials in the deployment platform's secret settings.

```
Browser (Next.js)                         Backend (FastAPI)
 ├─ LiveKit video/audio  ───────────────► LiveKit SFU (docker)
 └─ mic → AudioWorklet (16 kHz PCM) ─ws─► VAD segmenter
                                           └► ASR (Whisper)   ──► original caption (instant)
                                           └► Translator (streaming LLM, once per target language)
 captions + browser TTS  ◄────────ws───────── partial → final captions (fanned out per language)
```

## Run it (₹0, offline, mock AI)

```bash
cp .env.example .env              # leave GROQ_API_KEY empty => mock providers
docker compose up livekit         # video server (dev keys)
cd backend && pip install -r requirements.txt
uvicorn app.main:get_app --factory --port 8000
cd ../frontend && npm install && npm run dev     # http://localhost:3000
```

Open two browser windows, join the same room code, pick different languages. In mock mode captions look like
`[English] mock utterance 1` — that proves the full path (mic → VAD → pipeline → captions → voice) without any API.

## Real translation

Set `GROQ_API_KEY` in `.env` (free tier has rate limits; the code **respects** 429s, it does not rotate keys to evade them).
Model names are env-configurable (`GROQ_ASR_MODEL`, `GROQ_TRANSLATE_MODEL`).

**Measure before believing any latency claim:**
```bash
cd backend && python -m scripts.bench my_hindi_clip.wav --speak hi-en --listen en --runs 5
```
Live numbers are also at `GET /api/metrics` (p50/p95 per stage) and in the app's *Translation* tab.

## How latency is kept low
- Original-language caption is sent the moment ASR returns; translation streams in behind it.
- Translation streams token-by-token; the browser **speaks each completed sentence early** instead of waiting for the end.
- Each target language is translated **once** and fanned out; languages nobody selected are never processed.
- VAD hangover is configurable (`VAD_HANGOVER_MS`, default 450 ms) and is *included* in all reported end-to-end numbers.
- Every stage has a deadline; stale work is dropped with a visible status instead of arriving late.

## Meeting features
Pre-join screen (camera preview, mic level meter, device pickers), invite-link copy, gallery + **pin/spotlight**
(screen shares spotlight automatically), in-meeting **chat**, **raise hand** and emoji **reactions** (LiveKit data
channels, validated and rendered as inert text), and **host controls**: mute one/all, remove, lock room. The first
person in a room is host; if they leave, the longest-present participant is promoted.
Host actions go through the API (`/api/host/*`), which checks host status and then calls LiveKit's admin API with a
60-second server-side token; browsers never get admin rights.

## Honest limits (read these)
- Host mute/remove use LiveKit's Twirp admin API and are covered against a live local server by the two-browser E2E suite with synthetic camera/microphone devices.
- Chat is ephemeral (not stored, late joiners don't see history). Removed people can rejoin unless the room is locked. No waiting room.
- Still missing vs Meet/Teams: scheduling/calendar, recording, background blur, accounts, meeting summary, breakout rooms.
- The real-browser E2E suite verifies local LiveKit video/audio tracks, chat/reaction delivery, host mute/remove, mock captions, and responsive layout. It uses synthetic devices; physical camera/microphone hardware, screen sharing, and translated voice playback still need manual device checks.
- **Not true streaming ASR.** Whisper is called per utterance (VAD-cut). Expect roughly "end of sentence + ASR + first translated words". The adapter interface (`providers/base.py`) is where a streaming ASR (e.g. a WebSocket provider) plugs in.
- **Voice = browser speechSynthesis.** Free, zero server cost, consistent preset voice per speaker — but quality and language coverage depend on the listener's OS/browser. Missing voice ⇒ the UI says so and falls back to captions. Voice cloning is **not** implemented (needs consent flow + a provider).
- **Hinglish** support is: a roman-script ASR prompt + a translation prompt that treats code-switching as one language. Quality is **unmeasured** — benchmark with real Indian-accent recordings.
- Use **headphones**. "Pause my mic while voice plays" (default on) prevents echo loops but means you can't interrupt translated speech.
- Rooms live in memory in one process (no horizontal scaling yet); no accounts, DB, recording, or billing.
- Public deployment needs a real LiveKit host (+TURN), HTTPS/WSS, and a strong `JWT_SECRET`.

## Tests
```bash
cd backend && pip install -r requirements-dev.txt && pytest -q && ruff check app tests scripts
cd frontend && npm test && npm run typecheck && npm run build
```
Real-browser E2E (`e2e/`): two Chromium users with a fake mic, mock AI provider; covers lobby, pre-join, invite link,
translation both directions, host/guest UI, live media/data delivery, host actions, responsive layout (27 checks). See the header of `e2e/e2e.mjs` to run it.
Backend: VAD, registry, pipeline (partials, deadlines, stale-drop, rate-limit, hallucination filter), Groq adapters (fake HTTP), and WebSocket end-to-end (auth, isolation, capacity).

## Adding a language
Add one `Language(...)` in `backend/app/languages.py`. Nothing else changes.

## Layout
`backend/app` — `vad.py`, `pipeline.py`, `rooms.py`, `providers/`, `languages.py`, `latency.py`, `main.py`
`frontend` — `app/` pages, `components/Meeting.tsx`, `lib/useTranslation.ts` (WS + reconnect + TTS), `public/pcm-worklet.js`



## Windows local run (current project)

The mock setup needs Docker Desktop running. From PowerShell at the project root, copy `.env.example` to `.env`, then run `docker compose up -d livekit` and confirm `docker compose ps` reports `livekit` as Up.

In a second terminal, open `backend`, create and activate a Python 3.11 virtual environment, install `requirements-dev.txt`, then run:

```powershell
uvicorn app.main:get_app --factory --host 127.0.0.1 --port 8000 --env-file ..\.env
```

The `--env-file` flag is required for the backend process to read the root `.env` and use a Groq key. In a third terminal, open `frontend`, run `npm install` and `npm run dev`, then open `http://localhost:3000` in two browser windows.

To run API and LiveKit in Docker instead, use `docker compose --profile full up --build` and keep the frontend local. The API uses an internal address for LiveKit admin calls and returns the host address to browsers.

## Latency and validation limits

This version uses utterance-based Whisper transcription after VAD silence detection, not streaming ASR. It streams translation text after transcription; translated speech uses browser `speechSynthesis`, whose voice availability and latency vary by device. Therefore sub-second speech-to-speech is a future benchmark target, not a verified claim. E2E tests use mock AI and do not prove real LiveKit media or translation quality. See the current [Known limits](#known-limits) above.
