# Snipwise: design spec

Date: 2026-10-04
Status: draft, waiting for Nikhil's review
Name: **Snipwise** (chosen 2026-10-04). Folder: `snipwise/`.

## 1. Goal

A web app where a creator uploads a raw talking-head video (podcast, tutorial, vlog to camera) and gets back a tight edit: silences, filler words and bad takes removed, jump-cut zooms, burned-in captions and basic colour correction. The AI proposes the edit, the user reviews it, then the app renders it.

The project has two purposes:

1. **Learning and portfolio.** It must cover senior backend topics (auth, uploads, queues, retries, idempotency, rate limits, caching, cron, system design) and GenAI topics (speech to text, structured LLM output, evals, cost control, prompt injection) in one codebase that goes on GitHub.
2. **A real product later.** A free beta first, with subscriptions after version 1.

It needs no third-party platform approvals. The only outside services are the ElevenLabs speech-to-text API, the Gemini API and, after version 1, Stripe.

## 2. Scope

### In version 1

- Email and password accounts with a monthly free quota of 60 minutes of video.
- Upload of one video per project: MP4 or MOV, at most 15 minutes, at most 1080p, at most 2 GB, must have an audio track.
- Automatic pipeline: probe, transcribe, plan the edit.
- Review screen: transcript with kept and dropped segments, each drop with a reason. The user can flip any segment between keep and drop.
- Render on approval: cuts, jump-cut zooms, captions, colour correction. Download through a short-lived link.
- "Edit again" without transcribing again.
- Live progress, cancel, and retry from the failed stage.
- Rate limits, a per-user daily AI token cap, and automatic file deletion after 7 days.
- An eval set that scores the edit planner.

### Not in version 1 (in this order afterwards)

1. Deployment to a public URL with a spend cap.
2. Stripe subscriptions.
3. Editing the video by deleting words in the transcript.
4. Chat edits with an agent ("remove the part about pricing").
5. Local faster-whisper as a second `Transcriber` (optional, for learning how to run a model yourself).
6. Motion graphics templates.

Also out: multi-speaker handling, team accounts, mobile apps, RAG and pgvector, AI colour grading, any social platform publishing.

## 3. Stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js (UI only, no app logic in API routes) | Nikhil's choice. Kept thin: 5 screens. |
| API | Python 3.14, FastAPI, SQLAlchemy 2 async, Alembic, pydantic-settings, uv | Same stack and layout as `almarbatt_lite_py`, so auth is reused. |
| Database | Postgres 17 | Plain Postgres. pgvector is not needed in version 1. |
| Queue | Celery 5.6 with Redis as broker, Celery Beat for cron | Most widely known Python queue. Chains map onto pipeline stages. |
| Cache, limits, progress | Redis | Rate-limit counters, live progress, cancel flags. |
| File storage | S3 API. MinIO locally, S3 or R2 when deployed. | Presigned multipart uploads straight from the browser. |
| Speech to text | ElevenLabs Scribe v2 API | Covered by Nikhil's ElevenLabs subscription (list price $0.22 per hour of audio, checked 2026-10-04). Returns word timestamps and keeps filler words and false starts by default. Sits behind a `Transcriber` interface. |
| Silence detection | Gaps between word timestamps, computed in code | No extra model needed. Silero VAD is the fallback if gaps prove inaccurate. |
| LLM | Gemini (Flash class), `google-genai` SDK, strict JSON schema output | Nikhil's choice on cost. Sits behind an `LLM` interface. |
| Video | ffmpeg and ffprobe, called as subprocesses with argument lists | All cutting, zooming, captions and encoding. |

There is no Node backend. Node is installed only to run Next.js.

## 4. Architecture

```
Next.js UI ──▶ FastAPI API ──▶ Postgres
    │              │
    │              └──▶ Redis (Celery broker, progress, limits, cancel flags)
    │
    └── file chunks straight to S3 (presigned)
                         │
                         ▼
                  Celery workers
     1. Probe ─▶ 2. Transcribe ─▶ 3. Plan ─▶ (user reviews) ─▶ 4. Render
                         │
                         ▼
                  Result MP4 in S3
```

Rules:

- The API never touches video bytes. It creates rows, signs upload URLs and enqueues jobs.
- Workers do all slow work. Worker concurrency is limited so two ffmpeg renders do not starve the machine.
- Stages 1 to 3 run automatically, one after another, after the upload completes: each Celery task enqueues the next when its stage succeeds. Stage 4 runs only when the user approves a plan.
- Each stage records its result before the next one starts, so a retry resumes at the first stage that has not succeeded.

### Interfaces

Three small interfaces, each with a real and a fake implementation. The fakes are used in tests and in milestone 3.

| Interface | Real | Fake |
|---|---|---|
| `Transcriber.transcribe(audio_path) -> Transcript` | `ScribeTranscriber` | Returns a fixed transcript |
| `LLM.plan_edit(transcript, options) -> DropList` | `GeminiLLM` | Returns a fixed drop list, can be forced to fail |
| `Storage` (presign, upload, download, delete) | `S3Storage` | In-memory |

## 5. The pipeline

### Stage 1: probe

- Run ffprobe on the uploaded file.
- Reject with a clear message if: not a video, no audio track, longer than 15 minutes, larger than 1080p, or longer than the user's remaining quota.
- Save duration, resolution, frame rate and codec on the project.
- Extract audio to a 16 kHz mono WAV and store it at `projects/{project_id}/audio.wav`.

### Stage 2: transcribe

- Send the extracted audio to ElevenLabs Scribe v2 with word timestamps and verbatim output (`no_verbatim` left off), so "um", "uh" and false starts appear in the transcript.
- Save one `transcripts` row: the words with start and end times, the model name and the audio seconds billed.

### Stage 3: plan

Two sources of cuts are merged into one edit plan:

1. **Silences, by code.** Any gap between two words longer than 0.6 seconds is dropped, keeping 0.15 seconds of padding on each side.
2. **Fillers and bad takes, by Gemini.** The model receives the transcript as a numbered word list and returns **ranges of word indexes** to drop, each with a reason (`filler` or `retake`). For repeated attempts at a line it keeps the last complete take.

The model returns word indexes, never timestamps. Code maps indexes to times. This means a cut can never land inside a word and the model cannot invent a time.

The drop list is validated before use: schema check, indexes inside the transcript, no overlapping ranges, and the plan must keep at least 20% of the speech. If validation fails, the call is retried once with the error included. If it fails again, the plan falls back to silence cuts only and the review screen says so.

The result is saved as `edit_plans` version 1 with the token counts.

Each toggle the user chose (silences, fillers, best take) switches its part on or off.

### Stage 4: render

- Input: one edit plan version and the project's toggles.
- Build one ffmpeg filter graph: `trim` and `atrim` per kept segment, `setpts` to reset timestamps, `concat` to join.
- Jump-cut zooms: alternate kept segments between 100% and 108% scale, centre crop, so each cut looks intentional.
- Audio: a 10 millisecond fade at each cut to prevent clicks.
- Captions: word timings are remapped to the new timeline, written as an ASS subtitle file and burned in with libass. One caption style in version 1.
- Colour: one fixed mild correction preset (contrast and saturation). No AI grading.
- Encode H.264 video and AAC audio into MP4 and store it at `renders/{render_id}.mp4`.
- ffmpeg's progress output drives the progress bar.

Re-encoding is required because cuts must land on word boundaries, not on keyframes.

## 6. User journey and screens

1. **Sign up or log in.**
2. **Dashboard.** Project cards with thumbnail, title and status. A usage bar: "23 of 60 minutes used this month".
3. **New project.** Drag in a video. The browser checks type and size, then uploads in chunks straight to S3 with a progress bar. The user picks toggles: remove silences, remove fillers, keep best take, jump-cut zooms, captions, colour correction. The page states that files are deleted after 7 days.
4. **Processing.** Live steps: Checking video, Transcribing 40%, Planning edits. Cancel button. On failure, a clear message and a Retry button.
5. **Review.** The original video beside the transcript. Kept text is normal, dropped text is struck through with its reason. Clicking a segment flips it between keep and drop, which saves a new plan version. A Render button.
6. **Result.** The final video, "12:04 → 7:18, 4:46 removed", Download, Edit again, Delete.

The frontend is written mostly by Claude so Nikhil's time goes to the backend and AI.

## 7. Data model

All ids are UUID v7. All tables have `created_at`.

```
users ──< refresh_tokens
  │
  └──< projects ──1 transcripts
          │
          ├──< edit_plans ──< renders
          │
          └──< stage_runs
```

| Table | Columns |
|---|---|
| `users` | id, email (unique), password_hash, role |
| `refresh_tokens` | id, user_id, token_hash, expires_at, revoked_at |
| `projects` | id, user_id, title, status, options (JSONB: the toggles), source_key, source_size_bytes, duration_sec, width, height, fps, files_expire_at, deleted_at |
| `transcripts` | id, project_id (unique), language, model, audio_seconds, words (JSONB: text, start, end, type, confidence) |
| `edit_plans` | id, project_id, version, created_by (`ai` or `user`), segments (JSONB: start, end, action, reason), fallback_used, llm_model, input_tokens, output_tokens. Unique on (project_id, version). |
| `renders` | id, project_id, edit_plan_id, status, output_key, duration_sec, size_bytes |
| `stage_runs` | id, project_id, render_id (null except for render), stage, status, attempt, error_message, started_at, finished_at |

Decisions:

- **One transcript, many plans, many renders.** The source never changes, so it is transcribed once. Each render records the plan it used.
- **Words and segments are JSONB.** About 2,500 words for 15 minutes, always read together.
- **Monthly quota is calculated**, not stored: the sum of `duration_sec` for the user's projects created this month, including deleted ones. Deleting a project sets `deleted_at` and removes its files but keeps the row.
- **Every query is scoped to the owner.** A project that belongs to someone else returns 404.

### Project status

```
uploading → uploaded → processing → ready_for_review → rendering → done
```

Exits: `failed`, `cancelled`, `expired` (files deleted after 7 days). From `done`, "Edit again" goes back to `ready_for_review`. From `failed`, Retry goes back to `processing` or `rendering`.

Status changes use a guarded update (`UPDATE ... WHERE id = ? AND status IN (...)`) and check the row count, so two requests cannot both start the same run.

## 8. API

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/signup`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /users/me` (includes minutes used this month) |
| Projects | `POST /projects`, `GET /projects` (cursor pagination), `GET /projects/{id}`, `PATCH /projects/{id}`, `DELETE /projects/{id}` |
| Upload | `POST /projects/{id}/upload/start`, `POST /projects/{id}/upload/sign-part`, `POST /projects/{id}/upload/complete`, `POST /projects/{id}/upload/abort` |
| Pipeline | `POST /projects/{id}/process` (retry from the failed stage), `POST /projects/{id}/cancel`, `GET /projects/{id}/events` (SSE) |
| Review | `GET /projects/{id}/transcript`, `GET /projects/{id}/edit-plans/latest`, `POST /projects/{id}/edit-plans` |
| Render | `POST /projects/{id}/renders`, `GET /projects/{id}/renders/{render_id}` (returns a short-lived download URL) |

- `upload/complete` moves the project to `uploaded` and starts the pipeline.
- `upload/start` returns 403 if the user has no quota left this month, and 413 if the declared size is over 2 GB. The exact duration check happens in the probe stage.
- All request bodies are validated with Pydantic.
- All errors use `{ "code": "...", "message": "..." }` with status 401, 403, 404, 409, 413, 422 or 429.

### Progress

- Stage status lives in `stage_runs` in Postgres.
- The live percentage lives in a Redis key per project, updated by the worker.
- `GET /projects/{id}/events` sends one SSE event per second while a run is active, combining both, and closes when the run ends.

## 9. Failure handling

| Failure | Handling |
|---|---|
| ElevenLabs, Gemini or S3 temporary error | Celery retries up to 3 times with exponential backoff and jitter. |
| Corrupt, too long or unsupported video | No retry. Project is `failed` with a clear message. |
| Worker crashes mid-stage | Late acknowledgement, so the job is redelivered. Stages are idempotent: output keys are fixed, so a re-run overwrites. |
| Invalid plan from Gemini | Retry once with the error, then fall back to silence-only cuts (section 5). |
| "Process" or "Render" clicked twice | Guarded status update. The second request gets 409. |
| Cancel | The API sets a Redis cancel flag. The worker checks it between stages and while reading ffmpeg progress, then terminates ffmpeg. |
| Abandoned upload | A daily Celery Beat job aborts multipart uploads older than 24 hours. |
| File expiry | A daily Celery Beat job deletes files past `files_expire_at` and sets the project to `expired`. |

## 10. Security and limits

- Auth reused from `almarbatt_lite_py`: 15-minute access JWT, rotating refresh tokens stored as SHA-256 hashes.
- Ownership check on every project route.
- File type is decided by ffprobe, never by the file extension. S3 keys are ids, never the original filename.
- Presigned URLs are short-lived: 15 minutes for upload parts, 5 minutes for downloads.
- ffmpeg and ffprobe are run with argument lists, never through a shell.
- **Prompt injection.** The transcript is untrusted input: someone can say "ignore your instructions" in the video. The model can only return a drop list, the validation rules cap what a drop list can do, and the user reviews the plan before rendering.
- Rate limits on Redis: 15 per minute per IP on `/auth`, 250 per minute per user on the rest, and a tighter limit on `process` and `renders`. The algorithm is the sliding window counter unless the milestone 6 comparison of the five algorithms shows a better fit.
- AI cost: a daily token cap per user, checked before each Gemini call, plus a spend cap on the API key. Token counts are stored on each edit plan. Transcription cost is bounded by the monthly minutes quota.
- CORS allows only the frontend origin. Secrets come from environment variables.
- Gemini's free tier lets Google use inputs to improve its products. Free tier is for Nikhil's own test videos only. Real users require the paid tier.
- Audio is sent to ElevenLabs for transcription. Before real users upload, check ElevenLabs' data retention terms and state this in the app's privacy note.

## 11. Testing

- **Unit tests** for pure logic: drop list to time segments, merging and padding segments, remapping caption times after cuts, building the ffmpeg filter graph, the quota sum, the status rules.
- **API tests** with pytest against a test Postgres, using the fake transcriber, fake LLM and fake storage. Celery runs tasks inline in tests.
- **One end-to-end test** that sends a 20-second sample video through the real pipeline.

### Evals for the edit planner

- 10 to 15 short videos recorded by Nikhil with deliberate retakes, fillers and long pauses.
- Each has a hand-made label file: the time ranges that should be cut.
- Evals run on saved transcripts, so they need no transcription and cost only Gemini tokens.
- Scores per video and overall:
  - Precision: share of the cut time that should have been cut.
  - Recall: share of the time that should be cut that was found.
  - Hard checks: plan passes validation, no fallback used.
- Results are written to a table and compared after every prompt or model change.

## 12. Repository layout

```
snipwise/
  backend/
    src/
      auth/  users/  projects/  uploads/  pipeline/  transcripts/  edit_plans/  renders/
      config.py  database.py  main.py  celery_app.py
    alembic/
    tests/
  frontend/          Next.js
  evals/             labels, saved transcripts, runner script
  docs/
  docker-compose.yml Postgres, Redis, MinIO
```

Each backend folder follows the layout already used in `almarbatt_lite_py`: `router.py`, `schemas.py`, `models.py`, `service.py`, `dependencies.py`, `exceptions.py`.

### Local setup

- Docker Compose runs Postgres, Redis and MinIO. Docker is not installed on the Mac yet, so milestone 1 starts by installing OrbStack or Docker Desktop. The Homebrew Redis service must be stopped first, or Compose mapped to another port.
- `brew install ffmpeg-full` is required: the standard Homebrew ffmpeg 8.1 on the Mac has no subtitles filter.
- The API, the Celery worker, Celery Beat and Next.js each run in their own terminal.

## 13. Milestones

Each ends with something that runs.

| # | Milestone | Done when | Main concepts |
|---|---|---|---|
| 1 | Foundation | Sign up, log in, project CRUD. Postgres, Redis and MinIO running. | Reused auth, ownership checks, cursor pagination |
| 2 | Upload | A dropped video lands in MinIO in chunks. Bad files are rejected. | Presigned multipart upload, validation |
| 3 | Pipeline skeleton | The four stages run as Celery jobs with fake work. Progress, cancel and retry from the failed stage all work. | Queues, retries, idempotent stages, SSE, state machine |
| 4 | Transcribe and silence cuts | A real video comes out with silences removed. | ffprobe, calling a paid API safely (timeouts, retries, cost tracking), ffmpeg cutting |
| 5 | AI edit plan | Gemini removes fillers and bad takes. The review screen works. Evals produce numbers. | Structured output, validation and fallback, cost tracking, evals |
| 6 | Polish and limits | Zooms, captions, colour. Rate limits, quota, token cap, 7-day expiry. | ffmpeg filters, rate limiting algorithms, cron |

Rough pace: one milestone a week, version 1 by mid-November 2026. Milestone 5 is the most likely to run over. Late November is for deployment and Stripe. December is interview mode.

### How we build it

- Small steps, one concept at a time, with a stop for review after each.
- Claude writes boilerplate and the frontend. For interview-critical parts (the pipeline, retries, idempotency, the planner, rate limiting, evals), Nikhil either writes the code from pseudocode or reviews Claude's code with a planted bug to find, as he chooses per step.

## 14. Risks and things not yet verified

| Risk | Plan |
|---|---|
| Silences taken from gaps between word timestamps may be inaccurate (breaths, background noise, music). | Test on a real video at the start of milestone 4. If it is not good enough, add Silero VAD on the extracted audio. |
| ElevenLabs credits are shared across its products, and the plan and prices can change. | Store `audio_seconds` per transcript. Confirm the plan's included hours in the account before milestone 4. |
| Word timestamps can be off by 100 to 200 milliseconds. | Padding around cuts, and audio fades. Tune on the eval videos. |
| Gemini model names, prices and free-tier limits change often. | The model name and price table live in config. Confirm against current docs at milestone 5. |
| Bad-take detection quality is the core feature and is unproven. | Evals from milestone 5 onward. The review screen means a wrong cut is never rendered without the user seeing it. |

## 15. Amendments from planning (2026-10-04)

Decisions made while writing the implementation plans. Where one conflicts with an earlier section, this section wins.

- **Refresh token delivery.** The refresh token is sent as an httpOnly, SameSite=Lax cookie scoped to `/api/auth` (Secure in production). The access token is returned in the response body and kept in browser memory only. Nothing is stored in `localStorage`.
- **All routes are under `/api`.**
- **Project options are fixed at creation.** `PATCH /projects/{id}` changes the title only.
- **Extra columns.** `projects.upload_id` (the active multipart upload) and `edit_plans.fallback_reason` (`invalid_plan` or `daily_ai_limit`).
- **Thumbnails.** The probe stage stores one frame at `projects/{id}/thumb.jpg`, and `ProjectOut` carries a short-lived `thumbnailUrl`.
- **Extra endpoint.** `GET /projects/{id}/source-url` returns a 5-minute link to the original video for the review screen.
- **Saving user changes.** `POST /projects/{id}/edit-plans` takes `{baseVersion, flips: [segment indexes]}`. A stale `baseVersion` returns 409.
- **Uploader.** The browser uses a small custom chunk uploader (3 parts at a time, 3 retries per part), not Uppy.
- **Workers use a synchronous database session** (psycopg). The API stays async (asyncpg).
- **Stage hand-off.** Each pipeline task enqueues the next on success. Celery's `chain` is not used.
- **Redelivery timing.** The Redis visibility timeout is 40 minutes. A job whose child process dies is requeued at once; a job whose whole worker is hard-killed resumes after that timeout.
- **Cut rules.** Kept pieces shorter than 0.25 seconds are dropped. Word drops are cut 0.05 seconds inside the neighbouring kept words. Silences are recomputed over the words that remain after word drops.
- **Rate limits.** `POST process` and `POST renders`: 10 per minute per user. `sign-part`: its own limit of 1200 per minute per user, not counted in the general 250, so a 2 GB upload is never cut off.
- **Daily AI token cap:** 200,000 tokens per user per UTC day. Over the cap, the plan falls back to silence cuts.
- **Expiry.** `expired` can be reached from `uploaded`, `ready_for_review`, `done`, `failed` and `cancelled`, never from `processing` or `rendering`.
- **Evals live in `backend/evals/`**, not at the repository root.
- **Production (Milestone 7).** One Linux server with Docker Compose and Caddy, files in Cloudflare R2, CI on GitHub Actions, sign-ups capped by `beta_signup_limit` (default 50).
- **Local S3 image.** MinIO stopped publishing its Docker images in October 2025. Local development uses the community fork images `pgsty/minio` and `pgsty/mc`, which keep the same commands and ports.
