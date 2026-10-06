# Snipwise

An AI video editor for talking-head videos. Upload a raw recording and get back a tight edit: silences, filler words and bad takes removed, with jump-cut zooms, captions and colour correction. The AI proposes the cuts, you review them, then it renders.

Status: design and plans are written. No code yet.

## Documents

- Design spec: [docs/superpowers/specs/2026-10-04-snipwise-design.md](docs/superpowers/specs/2026-10-04-snipwise-design.md)
- Implementation plans, in order:
  1. [Foundation](docs/superpowers/plans/2026-10-04-m1-foundation.md)
  2. [Upload](docs/superpowers/plans/2026-10-04-m2-upload.md)
  3. [Pipeline skeleton](docs/superpowers/plans/2026-10-04-m3-pipeline-skeleton.md)
  4. [Transcribe and silence cuts](docs/superpowers/plans/2026-10-04-m4-transcribe-and-silence-cuts.md)
  5. [AI edit plan](docs/superpowers/plans/2026-10-04-m5-ai-edit-plan.md)
  6. [Polish and limits](docs/superpowers/plans/2026-10-04-m6-polish-and-limits.md)
  7. [Production](docs/superpowers/plans/2026-10-04-m7-production.md)

## Stack

Python and FastAPI, Postgres, Celery and Redis, S3-compatible storage, ffmpeg, ElevenLabs Scribe for transcription, Gemini for the edit plan, and a Next.js UI.

## Layout (planned)

```
snipwise/
  backend/     FastAPI app, Celery workers, tests, evals
  frontend/    Next.js UI
  deploy/      production Compose file, Caddyfile, scripts
  docs/        spec, plans, runbook, benchmarks
```
