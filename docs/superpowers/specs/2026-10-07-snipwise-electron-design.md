# Snipwise: design spec (Electron client + thin server)

Date: 2026-10-07
Status: draft, waiting for Nikhil's review
Supersedes: `2026-10-04-snipwise-design.md` (cloud web app). Where this document is silent, the rules of the old spec still apply; where they conflict, this document wins.

## 1. Goal

A Mac app for people who record talking-head videos or narrated screen recordings, have money, and do not want to edit. They drop a raw recording into the app, the app transcribes it locally, an AI proposes a tight edit (silences, filler words and bad takes removed, jump-cut zooms, captions, cleaned-up audio), they refine it by talking to the agent or clicking the transcript, and they export. The working model is Claude Code for video: local work, paid intelligence.

Two purposes, in this order:

1. **A product that ships.** Version 1 in front of ten paying-class beta users on a signed, notarized build. Mac only. No free tier beyond the beta.
2. **Backend learning.** The server is a small FastAPI service Nikhil writes himself: auth, rate limits, usage caps, an LLM proxy with validated structured output, evals. Topics the product no longer needs (presigned uploads, Celery, SSE) are practised elsewhere.

Positioning against Descript, Gling, Screen Studio and CapCut: fewer features, a better cut on two narrow inputs, local and private, conversational.

## 2. Scope

### In version 1

- Import one MP4 or MOV per project, any length, any resolution. Must have an audio track.
- Local pipeline: probe, 720p proxy, audio extraction, transcription with word timestamps, silence detection.
- AI edit plan from the server: fillers and bad takes as word-index ranges with reasons.
- Chat refinement: the user describes what to change; the agent revises the plan, audio settings or caption settings.
- Click any transcript segment to flip it between keep and drop.
- Plan versions, so any change can be undone by picking an earlier version.
- Preview on the proxy that skips dropped segments.
- Audio enhancement with two sliders (clean-up, tone) and a 20-second A/B excerpt.
- Export from the original file at native resolution: cuts, jump-cut zooms, burned-in captions, enhanced audio.
- Sign-in with Google, an email login link (Firebase handles identity) or email and password (the server's own); the FastAPI server owns users and tokens, a daily AI token cap per user, rate limits on the server.
- A signed, notarized `.dmg` with a sign-up cap for the beta.
- An eval set that scores the planner on Nikhil's own recordings.

Both talking-head and screen recordings go through the same cut pipeline in version 1. No input-specific behaviour yet.

### After version 1, in this order

1. Face-centred reframing for talking heads (a small Swift CLI helper that prints face boxes per sampled frame).
2. Screen-recording rules: a silence is only cut when the frames are static during it; automatic zooms toward on-screen change.
3. Stripe subscriptions and credits.
4. Rendered preview (a fast proxy render per plan) if segment-skipping preview proves too rough.
5. Auto-update (electron-updater).
6. Motion-graphic text overlays.

Out of scope entirely for now: Windows, Linux, iPad, multi-cam, multi-speaker, faceless or voiceover videos, thumbnail or title generation, script generation, AI colour grading, publishing to platforms, team accounts.

## 3. Stack

| Layer | Choice | Why |
|---|---|---|
| Desktop shell | Electron (current stable, Node 22), electron-vite, TypeScript | Fastest to ship for a Node developer; Claude Code is strongest in TypeScript and has a mature verification loop (Playwright for Electron, devtools). Swift is the version 2 option if users report the app feels heavy. |
| UI | React, Tailwind, shadcn/ui | Same toolkit as the NightOwl dashboard. Look and layout modelled on the Claude Desktop app. |
| Video and audio engine | `ffmpeg` and `ffprobe` as our own static LGPL build with `libass` and VideoToolbox, no `libx264` (Homebrew's GPL build in development only) | Hardware H.264 encode through `h264_videotoolbox`. LGPL build so the app can be sold. Spawned as subprocesses with argument lists, never a shell. See section 12. |
| Transcription | Prebuilt `whisper-cli` from whisper.cpp with Metal, model `ggml-large-v3-turbo-q5_0` | Free, runs on the user's Mac, word timestamps. Model downloaded on first run (about 600 MB) into Application Support with progress shown in the chat. Core ML is not used in version 1: it needs a custom build and a second encoder model. |
| Noise reduction | Prebuilt `deep-filter` (DeepFilterNet 3) binary, optional stage | Nikhil's locked voice chain. Bypassed when clean-up is zero. |
| Client state | JSON files in the project folder | No database in the client. Everything is inspectable and recoverable. |
| Server | Python 3.14, FastAPI, SQLAlchemy 2 async, Alembic, uv (already built) | Reuses the auth and layout already in `backend/`. |
| Server data | Postgres 17 (users, refresh tokens, usage ledger), Redis 7 (rate limits) | MinIO, S3 and Celery are removed. |
| LLM | Behind the existing `LLM` interface. Gemini Flash class to start, Claude as the swap candidate for the chat agent | Model and prompts live on the server so the cut improves without an app update. |

Rules that follow from the stack:

- **No native Node addons.** Every engine is a spawned binary. This avoids Electron ABI rebuilds and keeps notarization to "sign the nested binaries".
- **Bytes never leave the Mac.** Only transcript text, plan JSON and parameter objects go to the server.
- **The pipeline is a module with no Electron imports**, callable from a Node script, so the shell can be replaced later.

## 4. Architecture

```
┌──────────────────────── Electron app (Mac) ────────────────────────┐
│  Renderer (React)                                                  │
│    sidebar: projects │ chat thread │ workspace: player + transcript │
│          ▲ typed IPC (preload, zod-checked calls + progress events)│
│  Main process (Node)                                               │
│    project folders · pipeline module · spawns ffmpeg/whisper/dfn   │
│    HTTPS client to the server · tokens in safeStorage              │
└───────────────────────────────┬────────────────────────────────────┘
                                │ transcript, plan, params (text only)
                                ▼
┌──────────────────────── FastAPI server ────────────────────────────┐
│  /api/auth/*  /api/users/me  /api/plan  /api/chat  /api/usage/me   │
│  Postgres: users, refresh_tokens, usage_events   Redis: limits     │
│  LLM interface → Gemini / Claude                                   │
└────────────────────────────────────────────────────────────────────┘
```

### Processes

- **Main** owns the file system, the project folders, the pipeline, every subprocess, and the server connection. It is the only process that touches files, binaries or the network.
- **Preload** exposes a typed API and nothing else. Context isolation on, node integration off, sandbox on. The renderer receives plain data and progress events.
- **Renderer** is UI. It never resolves a path, spawns anything or calls the server.

### IPC surface (preload)

| Call | Purpose |
|---|---|
| `projects.list()`, `projects.import()`, `projects.importDropped(path)`, `projects.delete(id)` | Project folder lifecycle. `import` opens the file picker in main. `importDropped` takes the path preload obtained with `webUtils.getPathForFile`; main checks that it exists and is `.mp4` or `.mov`. |
| `projects.open(id)` | Returns the transcript, current plan, version list, chat and derived segments |
| `projects.relink(id)` | Opens the picker for a moved source, accepts it only if the partial hash matches |
| `pipeline.run(id)` | Runs every stage that has no output yet, emits progress |
| `pipeline.cancel(id)` | Kills the current subprocess, leaves completed stages |
| `plans.apply(id, plan)` | Saves a new plan version and returns derived segments |
| `plans.restore(id, version)` | Copies an old version into a new one and returns it |
| `chat.send(id, text)` | Sends a turn to the server, applies returned actions, saves chat |
| `audio.preview(id, params)` | Renders the 20-second A/B excerpt |
| `export.start(id, planVersion)`, `export.cancel(id)` | Final render, emits progress |
| `auth.signIn(method)`, `auth.logout()`, `auth.me()` | Account. Google and the email link run in the system browser and hand back through `snipwise://` |
| `shell.reveal(path)` | Show a file in Finder |
| events: `progress`, `stageDone`, `error` | Streamed from main |

Payloads are validated in main with zod before use. The renderer is treated as untrusted.

## 5. The project folder

`~/Movies/Snipwise/<project-id>/`, ids are UUID v7.

```
project.json      title, createdAt, source {path, sizeBytes, partialHash: sha256 of first+last 1 MB}, probe {duration, width, height, fps, codec}, options
thumb.jpg         one frame, for the sidebar
proxy.mp4         720p, h264_videotoolbox, same fps as source, 1-second keyframes
audio.wav         16 kHz mono, from the source
transcript.json   {model, language, words: [{text, start, end, confidence}]}
silences.json     [{start, end}] gaps between words > 0.6 s
plans/v1.json …   see section 7
chat.json         [{role, text, actions, createdAt}]
audio-enhanced/   <paramsHash>.wav, deep-filter output cached per parameter set
audio-preview/    excerpt renders per parameter set
exports/          1.mp4, 2.mp4 …
```

Rules:

- The source is referenced, never copied. If it moves, the app asks the user to relink it and checks the partial hash.
- **Every stage writes to a fixed path and skips if the file exists.** A crashed run resumes at the first missing output. "Edit again" costs nothing because transcript and proxy already exist. Deleting a stage file forces that stage to rerun.
- The project list is the folder listing, sorted by `createdAt`.

## 6. Pipeline

Stages, each a function in the pipeline module with the signature `(projectDir, onProgress, signal) => Promise<void>`:

| # | Stage | What it does |
|---|---|---|
| 1 | probe | `ffprobe` as JSON. Rejects files with no video or no audio stream. Saves duration, resolution, fps, codec. Writes one thumbnail frame. |
| 2 | proxy + audio | One `ffmpeg` pass: `-c:v h264_videotoolbox` scaled to 720p height with `-g <fps>` so every second has a keyframe for fast seeking, and `audio.wav` as 16 kHz mono PCM. Progress from `-progress pipe:1`. |
| 3 | model | Ensures the whisper model is present: streamed to a `.part` file, hashed while downloading, renamed when the SHA-256 matches, deleted when it does not. Skipped once the file exists. |
| 4 | transcribe | `whisper-cli` on `audio.wav` with word timestamps and a filler prompt ("Um, uh, so, like, you know…") so disfluencies are kept. Output normalised into `transcript.json`. Progress from the binary's stderr. |
| 5 | silences | Pure code. Any gap between consecutive words longer than 0.6 s is a silence, keeping 0.15 s of padding on each side. |
| 6 | plan | Calls `POST /api/plan` with the word list (index, text, start, end) and the project options. Saves `plans/v1.json`. Requires login. |

Stages 1 to 6 run automatically after import. Each stage posts a progress card in the chat. Cancel kills the running subprocess and keeps finished outputs.

### Cut rules (from the old spec, unchanged)

- The model returns **word index ranges**, never timestamps. Code maps indexes to times, so a cut never lands inside a word and the model cannot invent a time.
- Word drops are cut 0.05 s inside the neighbouring kept words. Silences are recomputed over the words that remain after word drops. Kept pieces shorter than 0.25 s are dropped. The plan must keep at least 20 percent of the speech.
- Overlapping or touching drops are merged. A merged drop takes the strongest reason, in the order retake, filler, user, silence. Segments are contiguous from 0 to the duration and rounded to 3 decimals.

### Preview

The player loads `proxy.mp4`. A frame callback (`requestVideoFrameCallback`, with `timeupdate` as the fallback) seeks past dropped segments. A toggle shows the original. This is instant and slightly jumpy at cut points; the rendered preview is the after-v1 fallback if that is not good enough to judge a cut.

The decision is taken in milestone 2 on one real 10 to 15 minute recording with at least 50 cuts. Two numbers are logged in development mode: overshoot (frame time when the skip fired minus the drop start, which is how much dropped content was shown) and seek latency (from the seek call to the `seeked` event). The preview passes if the p95 overshoot is 80 ms or less, the p95 seek latency is 150 ms or less, and Nikhil can judge 20 random cuts by ear. On a fail, the rendered preview moves to the top of the after-v1 list.

### Audio enhancement

One ffmpeg filter chain, Nikhil's locked voice chain, driven by two parameters:

| Slider | Range | Maps to |
|---|---|---|
| clean-up | 0 to 100 | 0 bypasses `deep-filter`; otherwise its attenuation limit scales with the value, then `highpass=f=80` |
| tone | -50 (warm) to +50 (bright) | a low shelf and a high shelf in opposite directions, ±3 dB at the ends |

Fixed after those: gentle `acompressor` and `loudnorm` to -14 LUFS. No `dynaudnorm`, no denoise filters inside ffmpeg, no exciters. Three presets (off, voice, podcast) are just slider pairs. `audio.preview` renders a 20-second excerpt from the middle of the kept speech per parameter set so the user can A/B before export.

### Export

Up to three passes from the **original** file at native resolution and fps. When clean-up is above zero: extract a 48 kHz mono WAV, run `deep-filter` on it (cached per parameter set), then render. When clean-up is zero the first two passes are skipped. The render is one `ffmpeg` run:

- `trim` and `atrim` per kept segment, `setpts`/`asetpts`, `concat`. One kept segment means no `split` and no `concat`.
- Jump-cut zooms: kept segments alternate between 100 and 108 percent scale, centre-cropped.
- Captions: word timings remapped to the new timeline, grouped into phrases of three to five words, written as one ASS file with one style, burned in with `libass`.
- Audio chain from the plan's parameters, plus a 10 ms fade at every cut.
- `h264_videotoolbox` video, AAC audio, MP4. Output to `exports/<n>.mp4`, then revealed in Finder.

## 7. Plans and the chat agent

### Plan file

```json
{
  "version": 3,
  "createdBy": "chat",
  "drops": [{"startWord": 120, "endWord": 131, "reason": "retake"}],
  "silenceOverrides": [4, 17],
  "options": {"silences": true, "fillers": true, "bestTake": true, "zooms": true},
  "audio": {"cleanup": 40, "tone": 0},
  "captions": {"enabled": true},
  "fallback": {"used": false, "reason": null},
  "note": "removed the second pricing explanation"
}
```

`createdBy` is `ai` (the plan stage), `user` (a click or a restore) or `chat`. `drops` are inclusive, zero-based word index ranges with reason `filler`, `retake` or `user`. `silenceOverrides` lists indexes into `silences.json` the user chose to keep, so a click can restore one silence. `fallback` records whether the plan stage fell back to silences only and why. Derived segments (kept time ranges) are computed on the client from drops, silences, overrides and the cut rules, never stored. Any version can be made current again, which creates a new version that copies it.

### Chat agent (server side)

`POST /api/chat` receives the last 20 chat turns, the numbered word list, the current plan and the project options. The server runs a tool-calling loop (at most three tool rounds) with these tools:

| Tool | Arguments | Client effect |
|---|---|---|
| `revise_plan` | `drops` (full replacement list with reasons) | New plan version |
| `set_audio` | `cleanup`, `tone` | New plan version, re-renders the A/B excerpt |
| `set_captions` | `enabled` | New plan version |
| `reply` | `text` | Message in the thread |

The response is `{message, actions[]}`. The client applies the actions, saves a version, and shows the message with a one-line summary card ("12:04 → 7:18, 3 segments restored"). Every tool argument is validated with the same rules as the plan endpoint before it is returned.

The transcript is untrusted input (someone can say "ignore your instructions" on camera). The agent can only return word indexes and bounded parameters, the user sees every change before export, and the daily token cap bounds the cost of any loop.

## 8. Server

What stays from the old spec: auth (15-minute access JWT, rotating refresh tokens as SHA-256 hashes), `GET /api/users/me`, ownership rules, `{code, message}` errors, Pydantic everywhere, CORS, secrets from environment.

What changes:

- **Removed:** projects, uploads, pipeline, transcripts, edit_plans, renders and stage_runs tables and routes. MinIO and Celery leave `docker-compose.yml`. Celery Beat jobs are gone.
- **Refresh token delivery:** the client is not a browser, so login and refresh return both tokens in the response body, and the Electron main process keeps them in `safeStorage`. Nothing is set in HTTP headers for the client to store.
- **Identity (changed 2026-10-07, "ornn pattern"):** no passwords. Firebase Auth does Google sign-in and the email login link (Firebase sends the email). The client sends the Firebase ID token to `POST /api/auth/firebase {idToken}`. The server verifies it with `firebase-admin` (behind a small `IdentityVerifier` interface with a fake for tests), finds or creates the user by `firebase_uid`, and returns its own access and refresh tokens plus the user. Email and password stays as a third sign-in method (kept for backend learning, decided 2026-10-07): `POST /api/auth/signup` and `POST /api/auth/login` remain. `users.password_hash` becomes nullable (Firebase-only users have none) and `users.firebase_uid` (unique, nullable) is added. One account per email: a Firebase sign-in with a verified email links to an existing password account; password sign-up for an email that already exists returns 409; password login on an account with no password returns the normal 401. Google sign-in cannot run inside an Electron window, so both methods open the system browser and hand back to the app through `snipwise://` with a short-lived, single-use value, never the server's tokens. Own Google OAuth and own magic links may replace Firebase later.
- **Sign-up:** the first successful `POST /api/auth/firebase` for a new `firebase_uid` creates the account. It counts users inside that transaction and returns 403 `signup_closed` once `beta_signup_limit` (default 50) is reached.
- **New table `usage_events`:** id, user_id, kind (`plan` or `chat`), model, input_tokens, output_tokens, created_at. The daily cap is a sum over this table.
- **New endpoints:**

| Endpoint | Body | Returns |
|---|---|---|
| `POST /api/plan` | `{words: [{text, start, end}], options}` | `{drops, fallbackUsed, fallbackReason}` |
| `POST /api/chat` | `{messages, words, plan, options}` | `{message, actions}` |
| `GET /api/usage/me` | | tokens used today, cap, resets at |

Words carry their timings because the 20 percent rule is measured by summed word duration, not word count.

Planner behaviour is unchanged: strict JSON schema output, validation (indexes in range, no overlaps, at least 20 percent kept), one retry with the error, then a silence-only fallback flagged to the user. Drops for an option the user switched off are discarded. When both fillers and best-take are off, no model call is made.

Limits: 15 per minute per IP on `/api/auth/*`, 20 per minute per user on `/api/plan` and `/api/chat`, 200,000 tokens per user per UTC day (over the cap: plan falls back to silences only, chat returns 429 with the reset time). The limiter fails open when Redis is unreachable.

### Hosting

One VPS (Hetzner or DigitalOcean, the smallest size that runs three containers) with Docker Compose: the API, Postgres and Redis, behind Caddy for TLS. A nightly `pg_dump` to the VPS disk and a weekly copy off the box. Secrets in a server-side `.env`, never in the image. A paid Gemini key. GitHub Actions builds the API image on every push to `main`; deploying is a manual `docker compose pull && up -d` on the box. This is the old milestone 7 design minus R2.

Evals live in `backend/evals/`: 10 to 15 of Nikhil's recordings with hand-labelled cut ranges, run on saved transcripts, scored for precision and recall, compared after every prompt or model change.

## 9. UI

Modelled on the Claude Desktop app: a calm three-pane window.

- **Sidebar** (collapsible): project list with thumbnail, title, duration, status. New project is a drop zone and a file picker.
- **Chat thread**: progress cards during the pipeline, the proposal card after planning, user messages, agent replies with summary cards. The composer accepts text and a dropped file.
- **Workspace** (widest): the player on top with play, scrub, original/edited toggle. Below it the transcript: kept text normal, dropped text struck through with its reason on hover, click to flip. A small audio panel with the two sliders, preset buttons, and A/B play. The Export button sits on the current plan's card and in the workspace header.
- **Settings**: account, model download status, binaries' versions, project folder location.

States the UI must handle: not logged in (sign in), sign-ups closed, model not downloaded, source file missing (relink), pipeline failed at stage N with retry, over the daily cap (shows when it resets), offline (everything local still works; plan and chat show a clear message). A first-run privacy notice states what leaves the Mac.

## 10. Testing

- **Vitest (client)**: index-to-time mapping, silence recomputation, segment merging and minimum length, caption remap and phrase grouping, ffmpeg argument builders for proxy, excerpt and export, plan validation, IPC payload schemas.
- **Pytest (server)**: planner validation and fallback with the fake LLM, chat tool parsing, token cap, rate limits, auth (existing tests stay).
- **Playwright for Electron**: one smoke test that launches the app, imports a 20-second sample, waits for the pipeline with the server mocked, flips one segment, exports, and checks the output duration with ffprobe.
- **Evals**: the planner eval set, run on demand.

## 11. Security and privacy

- Only transcript text, plan JSON and parameter objects are sent to the server. No audio, no video, no file names. The app states this in Settings and on first run.
- Subprocesses run with argument lists. Paths come from the file picker or the project folder, never from the renderer directly.
- Renderer: context isolation, sandbox, no remote content. Content Security Policy allows only local resources.
- Binaries are bundled inside the app, signed with the app, and verified by the hardened runtime. Model files are downloaded over HTTPS from a pinned URL and checked against a published SHA-256.
- Tokens live in `safeStorage` (Keychain-backed). Logout deletes them.
- The server validates the model's drop list; the client re-validates the final segments after applying the 0.25 s minimum-keep rule and shows a warning, not an error, if the kept share falls under 20 percent.

## 12. Distribution

- `electron-builder`, Developer ID Application certificate, hardened runtime, entitlements for file access and the JIT the renderer needs.
- Every nested binary (`ffmpeg`, `ffprobe`, `whisper-cli`, `deep-filter`) is signed with the hardened runtime before the app bundle is signed.
- `xcrun notarytool submit --wait`, then `stapler`. The beta is arm64 only, stated on the download page.
- **ffmpeg is our own build.** No trustworthy prebuilt LGPL ffmpeg for macOS with `libass` and VideoToolbox exists, and the Homebrew build is GPL and linked against `/opt/homebrew`. `app/scripts/build-ffmpeg.sh` configures `--disable-gpl --enable-libass --enable-videotoolbox --enable-audiotoolbox` and links statically. It is built in milestone 5 so milestone 6 is not blocked on it. Development machines use the Homebrew ffmpeg behind a `--allow-gpl-dev` flag on the binary check; `verify-binaries` refuses a GPL build without that flag.
- Binaries live in `app/resources/bin/` (ignored by git) and are fetched by `app/scripts/fetch-binaries.mjs`. At runtime `main/bins.ts` resolves them from `process.resourcesPath` when packaged and from the app path in development; `SNIPWISE_BIN_DIR` overrides both for scripts and tests.
- The one-time setup (certificate, app-specific password, entitlements) is done by Nikhil with Claude in one session, not left to the agent.
- No auto-update in version 1. The beta download page carries the version.

## 13. Milestones

| # | Milestone | Done when |
|---|---|---|
| 1 | Shell | Electron app opens with the three panes. Drop a video, see it probed, see the proxy play in the workspace. Project folder written. |
| 2 | First edit | Transcript appears, silences are cut, the preview skips them, export produces a shorter MP4. No AI, no server. Preview quality decision taken. |
| 3 | Planner | Starts by finishing the server auth endpoints (tokens in the body). Then the `plan` endpoint with validation, fallback, token cap and rate limit. Proposal card with fillers and retakes removed. Evals produce numbers. |
| 4 | Conversation | `chat` endpoint and tools. Typing "put the pricing part back" revises the plan. Click-to-flip. Plan versions. |
| 5 | Polish | Captions, zooms, audio sliders with the A/B excerpt. Settings screen. The LGPL ffmpeg build. Memory check on a 60-minute file. |
| 6 | Ship | Sign-up and login in the app, every UI state handled, server deployed on the VPS, signed and notarized dmg, first ten beta users. |

Plan files: `docs/superpowers/plans/2026-10-07-m1-shell.md` to `m6-ship.md`.

Pace: about one milestone a week. Milestones 3 and 4 are Nikhil's backend work and the most likely to run over. Target for version 1 is the end of November 2026. December is interview mode.

### How we build it

- Claude writes the Electron app, the UI and the pipeline module. Nikhil reviews the pipeline module and the IPC boundary.
- Nikhil writes the server: planner, validation, chat tools, usage ledger, limits, evals. Claude writes boilerplate and tests on request.
- Small tasks with a stop for review after each. Agent tasks are scoped to one IPC call, one stage or one screen at a time.

## 14. Risks and things not yet verified

| Risk | Plan |
|---|---|
| Whisper drops fillers even with the prompt. | Measure on the eval recordings in milestone 2. Fallback: detect short low-energy utterances between words as filler candidates; or an ElevenLabs Scribe option behind the `Transcriber` interface for users who opt in to cloud transcription. |
| Segment-skipping preview is too jumpy to judge a cut. | Decide in milestone 2. Fallback is a proxy render per plan (about 30 s for 15 minutes with the hardware encoder). |
| The development ffmpeg lacks `libass` or `h264_videotoolbox`. | `verify-binaries` checks `-encoders`, `-filters` and `-L` on the exact binary in milestone 1. |
| The static LGPL ffmpeg build is real work (libass, freetype, fribidi, harfbuzz). | Scheduled in milestone 5, not 6. If it slips, the beta ships with a note and the build moves to the first update. |
| `split` and `trim` over hundreds of kept segments on a 60-minute file buffer frames and may exhaust memory. | Measure in milestone 2 with a long file. Fallback is `select`/`aselect` with `between()`, which changes how fades and zooms are applied. |
| whisper.cpp word timestamps drift because they come from tokens. | Test `--dtw` on the eval recordings in milestone 2. Padding around cuts absorbs small drift. |
| Notarization fails on nested binaries or Apple-side delays. | Milestone 6 is a paired session. Sign inside-out, keep the notarytool log. |
| Large source files make the proxy stage slow on Intel Macs. | Beta is Apple Silicon only, stated on the download page. |
| Electron memory grows over a long session. | Watch in milestone 5 with a 60-minute file. Keep transcript rendering virtualised. |
| Planner quality on retakes is unproven. | Evals from milestone 3. The user reviews every cut before export. |
| Gemini free tier uses inputs for training. | Free tier for Nikhil's tests only. Paid tier before any beta user. |
