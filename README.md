# Snipwise

An AI video editor for talking-head videos and narrated screen recordings, as a Mac app. Drop a raw recording in, the app transcribes it on your machine, an AI proposes a tight edit (silences, filler words and bad takes removed, jump-cut zooms, captions, cleaned-up audio), you refine it by talking to the agent or clicking the transcript, then export. Video never leaves the Mac; only transcript text goes to a small server that holds the AI prompts.

Status: Electron pivot on 2026-10-07. Server auth in progress (milestone 3, Task 1). Client not started.

## Documents

- Design spec: [docs/superpowers/specs/2026-10-07-snipwise-electron-design.md](docs/superpowers/specs/2026-10-07-snipwise-electron-design.md)
- Implementation plans, in order:
  1. [Shell](docs/superpowers/plans/2026-10-07-m1-shell.md)
  2. [First edit](docs/superpowers/plans/2026-10-07-m2-first-edit.md)
  3. [Planner](docs/superpowers/plans/2026-10-07-m3-planner.md)
  4. [Conversation](docs/superpowers/plans/2026-10-07-m4-conversation.md)
  5. [Polish](docs/superpowers/plans/2026-10-07-m5-polish.md)
  6. [Ship](docs/superpowers/plans/2026-10-07-m6-ship.md)
- The earlier cloud web-app design and its plans are kept in [docs/superpowers/plans/archive/](docs/superpowers/plans/archive/).

## Stack

Client: Electron with electron-vite, React, TypeScript, Tailwind and shadcn/ui. Prebuilt `ffmpeg`, `ffprobe`, `whisper-cli` (whisper.cpp) and `deep-filter` binaries, spawned as subprocesses. Project state as JSON files in `~/Movies/Snipwise/`.

Server: Python and FastAPI, Postgres, Redis, an LLM behind an interface (Gemini to start). Auth, rate limits, a daily token cap, the edit planner and the chat agent.

## Layout

```
snipwise/
  app/               Electron client
    src/main         file system, pipeline orchestration, subprocesses, server client
    src/preload      typed IPC surface
    src/renderer     React UI: sidebar, chat thread, workspace
    src/pipeline     Electron-free pipeline module (stages, cut rules, ffmpeg args)
    resources/bin    fetched binaries (not in git)
    scripts/         fetch-binaries, verify-binaries, build-ffmpeg
  backend/           FastAPI app, tests, evals
  docs/              spec, plans
```
