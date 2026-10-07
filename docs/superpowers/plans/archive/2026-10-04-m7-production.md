# Milestone 7: Production Implementation Plan

> **How this plan is executed:** learning mode, not an autonomous agent run. One task at a time, in small steps, with a stop for review after each. Each task has a **Who** line: `Claude` writes boilerplate and UI; `Nikhil` writes interview-critical code from the signatures and tests here, or reviews Claude's version with a planted bug, as he chooses per task. Steps that buy something, create an account or publish something are always done by Nikhil. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Version 1 runs at a public HTTPS address as a free beta, with backups, monitoring, spend limits and a tested recovery path.

**Architecture:** One Linux server runs everything with Docker Compose: Caddy (HTTPS and reverse proxy), the Next.js frontend, the API, a Celery worker, Celery Beat, Postgres and Redis. Video files live in Cloudflare R2 through the same S3 interface used locally. GitHub Actions runs the tests on every push.

**Tech Stack:** Docker, Docker Compose, Caddy, Cloudflare R2, GitHub Actions, uvicorn. Builds on Milestones 1 to 6.

**Spec:** `docs/superpowers/specs/2026-10-04-snipwise-design.md` (section 2, "Not in version 1", item 1: deployment to a public URL with a spend cap). Stripe is the next item after this plan and is not part of it.

## Global Constraints

- All earlier constraints still apply.
- Production runs with `ENVIRONMENT=production`, `PIPELINE_MODE=real`, `TRANSCRIBER=scribe`, `LLM=gemini`, `STORAGE_BACKEND=s3`. The app refuses to start in production with any fake.
- Secrets exist only in the server's env file (mode 600) and in GitHub Actions secrets. They are never committed and never logged.
- Gemini runs on the paid tier in production (the free tier lets Google use inputs to improve its products).
- All traffic is HTTPS. The refresh cookie is `Secure`. CORS allows only the real frontend origin.
- Only Caddy is reachable from the internet (ports 80 and 443, plus SSH on 22). Postgres, Redis, the API and the frontend are not published on the host.
- The API trusts `X-Forwarded-For` only from Caddy.
- Server: Ubuntu 24.04, at least 4 vCPU, 8 GB RAM, 80 GB disk. Worker concurrency stays 2.
- Beta sign-ups are capped (`beta_signup_limit`, default 50) so cost has a ceiling.
- Database backups run nightly and are kept 14 days. A restore is tested once before launch.
- Logs are JSON lines on stdout with a request id. Docker rotates them (10 MB, 5 files).

## Review Focus

1. The server reboots while a job is running: every service comes back on its own and the job finishes without anyone touching it (Task 7 drill).
2. A deploy happens during a render: the render is not lost (Task 7 drill).
3. The disk fills up: the readiness check reports it before uploads and renders start failing (Task 1 test).
4. A client sends a fake `X-Forwarded-For` header on every request: the rate limit still applies to its real address (Task 5 check).
5. A backup exists but has never been restored: prove the restore works (Task 6 drill).

## File Structure

```
backend/
  Dockerfile  .dockerignore
  src/config.py            production validation, beta_signup_limit
  src/logging_setup.py     JSON logging
  src/middleware.py        request id + access log + security headers
  src/main.py              health/ready, docs off in production
frontend/
  Dockerfile  .dockerignore  next.config.ts (output: "standalone")
  src/app/privacy/page.tsx  src/app/terms/page.tsx
deploy/
  docker-compose.prod.yml  Caddyfile  .env.prod.example
  deploy.sh  backup.sh  server-setup.md
.github/workflows/ci.yml
docs/runbook.md  docs/benchmarks.md  README.md
```

---

### Task 1: Production settings, health checks and logging

**Who:** Nikhil

**Files:**
- Create: `backend/src/logging_setup.py`, `backend/src/middleware.py`
- Modify: `backend/src/config.py`, `backend/src/main.py`, `backend/src/auth/service.py`, `backend/src/auth/exceptions.py`
- Test: `backend/tests/test_production.py`

**Interfaces:**
- Produces:
  - Settings: `beta_signup_limit: int = 50`, `min_free_disk_gb: float = 5.0`. A `model_validator` that, when `environment == "production"`, raises on: a JWT secret shorter than 32 characters, `frontend_origin` not starting with `https://`, `pipeline_mode != "real"`, `transcriber != "scribe"`, `llm != "gemini"`, `storage_backend != "s3"`.
  - `auth.service.signup`: when the number of users is at or above `beta_signup_limit` → `SignupsClosed` (403, `signups_closed`, "The beta is full for now.").
  - `GET /api/health` → 200 `{"status": "ok"}` with no dependencies (liveness).
  - `GET /api/health/ready` → 200 `{"status": "ok", "checks": {"database": "ok", "redis": "ok", "disk": "ok"}}`, or 503 with the failing check set to `"fail"`. Checks: `SELECT 1`, Redis `PING`, and free space in the temp directory at least `min_free_disk_gb`.
  - In production, `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)`.
  - `middleware.RequestContextMiddleware`: takes `X-Request-ID` from the request if it is 1 to 64 safe characters, else makes a UUID; returns it in the `X-Request-ID` response header; writes one log line per request with `request_id`, `method`, `path`, `status`, `duration_ms`, `user_id` (when known). It never logs headers, cookies, query strings or bodies. It adds `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer` to every response.
  - `logging_setup.configure_logging()`: JSON lines to stdout for the API and for Celery (`project_id`, `stage`, `attempt` on stage logs).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_production.py
GOOD = dict(environment="production", jwt_secret="a" * 32, jwt_refresh_secret="b" * 32, frontend_origin="https://app.example.com",
            pipeline_mode="real", transcriber="scribe", llm="gemini", storage_backend="s3")

def test_production_settings_accept_a_safe_config(base_env):
    Settings(**base_env, **GOOD)

@pytest.mark.parametrize("bad", [{"jwt_secret": "short"}, {"frontend_origin": "http://app.example.com"}, {"pipeline_mode": "fake"},
                                 {"transcriber": "fake"}, {"llm": "fake"}, {"storage_backend": "memory"}])
def test_production_settings_reject_unsafe_values(base_env, bad):
    with pytest.raises(ValidationError):
        Settings(**base_env, **{**GOOD, **bad})

async def test_signups_close_at_the_beta_limit(client, settings_override):
    settings_override(beta_signup_limit=1)
    assert (await client.post("/api/auth/signup", json={"email": "a@test.com", "password": "password123"})).status_code == 201
    res = await client.post("/api/auth/signup", json={"email": "b@test.com", "password": "password123"})
    assert res.status_code == 403 and res.json()["code"] == "signups_closed"

async def test_ready_reports_each_check(client, monkeypatch, settings_override):
    assert (await client.get("/api/health/ready")).json()["checks"] == {"database": "ok", "redis": "ok", "disk": "ok"}
    settings_override(min_free_disk_gb=10**9)
    res = await client.get("/api/health/ready")
    assert res.status_code == 503 and res.json()["checks"]["disk"] == "fail" and res.json()["checks"]["database"] == "ok"

async def test_liveness_does_not_touch_dependencies(client, monkeypatch):
    monkeypatch.setattr("src.main.engine", None)
    assert (await client.get("/api/health")).status_code == 200

async def test_request_id_and_security_headers(client):
    res = await client.get("/api/health", headers={"X-Request-ID": "abc-123"})
    assert res.headers["x-request-id"] == "abc-123" and res.headers["x-content-type-options"] == "nosniff"
    bad = await client.get("/api/health", headers={"X-Request-ID": "x" * 500})
    assert len(bad.headers["x-request-id"]) == 36

async def test_access_log_has_no_secrets(client, caplog):
    await client.post("/api/auth/login?token=leak-me", json={"email": "a@test.com", "password": "hunter2-hunter2"}, headers={"Authorization": "Bearer leak-me-too"})
    text = caplog.text
    assert "hunter2" not in text and "leak-me" not in text and '"path": "/api/auth/login"' in text

def test_docs_are_off_in_production(production_app_client):
    assert production_app_client.get("/docs").status_code == 404 and production_app_client.get("/openapi.json").status_code == 404
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/test_production.py -v`
Expected: FAIL.

- [ ] **Step 3: Write the validator, the sign-up limit, the two health routes, the middleware and the logging setup.**

- [ ] **Step 4: Run every test**

Run: `uv run pytest -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: production settings check, readiness, request logging, beta limit"
```

---

### Task 2: Container images and the production Compose file

**Who:** Claude

**Files:**
- Create: `backend/Dockerfile`, `backend/.dockerignore`, `frontend/Dockerfile`, `frontend/.dockerignore`
- Create: `deploy/docker-compose.prod.yml`, `deploy/Caddyfile`, `deploy/.env.prod.example`
- Modify: `frontend/next.config.ts` (`output: "standalone"`)

**Interfaces:**
- Produces:
  - `backend/Dockerfile`: base `python:3.14-slim`; installs `ffmpeg` and `fonts-noto-core` with apt; installs dependencies with `uv sync --frozen --no-dev`; runs as a non-root user; no default command (each service sets its own).
  - `frontend/Dockerfile`: multi-stage Node build, `NEXT_PUBLIC_API_URL` as a build argument, runs the standalone server as a non-root user on port 3000.
  - `deploy/docker-compose.prod.yml` services, all with `restart: unless-stopped` and log rotation (`max-size: 10m`, `max-file: 5`):
    - `caddy`: ports 80 and 443, volumes for the Caddyfile, certificates and config.
    - `frontend`.
    - `api`: `uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 2 --proxy-headers --forwarded-allow-ips "*"` (safe because the API port is not published and only Caddy can reach it), healthcheck on `/api/health`.
    - `worker`: `celery -A src.celery_app worker --concurrency=2 --loglevel=info --max-tasks-per-child=20`, `stop_grace_period: 20m`.
    - `beat`: `celery -A src.celery_app beat --loglevel=info`.
    - `migrate`: one-off, `alembic upgrade head`, `restart: "no"`; `api`, `worker` and `beat` depend on it finishing successfully.
    - `postgres` (named volume, healthcheck) and `redis` (`--appendonly yes`, named volume). Neither publishes a port.
  - `deploy/Caddyfile`: `app.{$DOMAIN}` → `frontend:3000`; `api.{$DOMAIN}` → `api:8000` with `flush_interval -1` (so SSE events are not buffered) and `header Strict-Transport-Security "max-age=31536000"`.
  - `deploy/.env.prod.example`: every variable the app reads, with empty values and one comment line each.

- [ ] **Step 1: Write the two Dockerfiles and `.dockerignore` files.**

- [ ] **Step 2: Build both images locally**

Run: `docker build -t snipwise-backend backend && docker build -t snipwise-frontend --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000/api frontend`
Expected: both builds succeed.

- [ ] **Step 3: Check the backend image has what renders need**

Run: `docker run --rm snipwise-backend sh -c "ffmpeg -hide_banner -filters | grep subtitles && fc-list | grep -i noto | head -1 && id -u"`
Expected: a `subtitles` line, a Noto font line, and a user id that is not `0`.

- [ ] **Step 4: Run the test suite inside the image**

Run the image against the local Compose Postgres and Redis: `docker run --rm --network host --env-file backend/.env snipwise-backend uv run pytest -q`
Expected: all passed (this proves the Linux ffmpeg build behaves like the Mac one).

- [ ] **Step 5: Write the Compose file, Caddyfile and env example, then start the stack locally**

With `DOMAIN=localhost` and MinIO added through a local override file, run `docker compose -f deploy/docker-compose.prod.yml up -d`.
Expected: `docker compose ps` shows every service healthy or running and `migrate` exited with 0.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "build: container images and production compose stack"
```

---

### Task 3: Continuous integration

**Who:** Claude writes the workflow. Nikhil creates the GitHub repository and pushes.

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: a workflow on `push` and `pull_request` with two jobs.
  - `backend`: services `postgres:17` and `redis:7`; installs ffmpeg and `fonts-noto-core`; `uv sync --frozen`; `uv run ruff check .`; `uv run pytest -q` (unit, API, real-ffmpeg and rate-limit tests; tests marked `integration` or `live` are not run).
  - `frontend`: `npm ci`, `npm run lint`, `npm run build`.

- [ ] **Step 1: Write the workflow.**

- [ ] **Step 2: Nikhil creates the repository and pushes**

Decide public or private first. Before the first push, run `git log -p | grep -i -E "api_key|secret|password" | head` and confirm no real secret was ever committed.
Expected: nothing but variable names and test values.

- [ ] **Step 3: Check the first run**

Expected: both jobs are green on GitHub. If a test passes locally and fails in CI, fix the cause (usually a missing system package or a timing assumption), do not skip the test.

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "ci: run backend and frontend checks on every push"
```

---

### Task 4: Object storage on Cloudflare R2

**Who:** Nikhil (account and bucket), Claude (commands and checks)

**Files:**
- Modify: `deploy/.env.prod.example`, `docs/runbook.md`

**Interfaces:**
- Consumes: `S3Storage`, the storage contract tests.
- Produces: a private R2 bucket with:
  - An API token limited to that bucket (object read and write).
  - A CORS rule: allowed origin `https://app.<domain>`, methods `PUT` and `GET`, allowed header `content-type`, exposed header `ETag`.
  - Lifecycle rules as a safety net behind the app's own clean-up: abort incomplete multipart uploads after 1 day, delete objects under `projects/` and `renders/` after 8 days. Objects under `backups/` are deleted after 14 days.
  - Env values: `S3_ENDPOINT_URL` and `S3_PUBLIC_ENDPOINT_URL` set to the account's R2 endpoint, `S3_REGION=auto`.

- [ ] **Step 1: Read the current R2 docs** for S3 compatibility, presigned URLs, CORS and lifecycle rules, and note anything that differs from MinIO in `docs/runbook.md`.

- [ ] **Step 2: Create the bucket, the token, the CORS rule and the lifecycle rules.**

- [ ] **Step 3: Run the storage contract tests against R2**

Run locally with the R2 values in the environment: `uv run pytest tests/storage -m integration -v`
Expected: all passed. This covers multipart, wrong ETag, abort, listing uploads, delete by prefix and presigned links.

- [ ] **Step 4: Check the browser path**

Point the local app at R2 (temporarily add `http://localhost:3000` to the CORS rule) and upload a 100 MB video from the browser.
Expected: it completes, and the Network tab shows the `ETag` header is readable. Remove the localhost origin afterwards.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "docs: R2 storage setup"
```

---

### Task 5: The server and the first deploy

**Who:** Nikhil, with Claude guiding each command

**Files:**
- Create: `deploy/server-setup.md`, `deploy/deploy.sh`
- Modify: `docs/runbook.md`

**Interfaces:**
- Consumes: the production Compose stack, the R2 bucket, a domain.
- Produces:
  - A server reachable at `https://app.<domain>` and `https://api.<domain>`.
  - `deploy/server-setup.md`: the exact steps used, so the server can be rebuilt.
  - `deploy/deploy.sh`: `git pull`, build images, run `migrate`, `up -d`, then wait for `/api/health/ready` to return 200 and fail loudly if it does not within 2 minutes.

- [ ] **Step 1: Nikhil rents the server and points DNS**

Any provider that meets the size in Global Constraints. Create `A` records for `app` and `api`.
Run: `dig +short app.<domain> api.<domain>`
Expected: both print the server's IP.

- [ ] **Step 2: Harden the server**

Create a non-root user with sudo, allow SSH by key only (`PasswordAuthentication no`, `PermitRootLogin no`), enable `ufw` with only 22, 80 and 443 open, turn on unattended security upgrades, install Docker.
Run from another machine: `nmap -Pn -p 22,80,443,5432,6379,8000,3000 <server ip>`
Expected: only 22, 80 and 443 are open.

- [ ] **Step 3: Configure production**

Clone the repo, copy `.env.prod.example` to `deploy/.env.prod`, `chmod 600` it, and fill it: new JWT secrets (`openssl rand -hex 32`), a strong Postgres password, the R2 values, the ElevenLabs key, the Gemini paid-tier key and model, `FRONTEND_ORIGIN=https://app.<domain>`, `DOMAIN=<domain>`.

- [ ] **Step 4: First deploy**

Run: `./deploy/deploy.sh`
Expected: it ends with "ready". `curl -s https://api.<domain>/api/health/ready` returns all three checks `ok`. The browser shows a valid certificate on both hostnames.

- [ ] **Step 5: Smoke test in the browser**

1. Sign up, log in, reload: still logged in. The `refresh_token` cookie is `Secure` and `HttpOnly`.
2. Upload a 2-minute recording: progress events arrive one per second (not all at once at the end).
3. Review, render with captions, download.
4. `https://api.<domain>/docs` returns 404.

- [ ] **Step 6: Check the proxy and rate limit**

Run: `for i in $(seq 1 16); do curl -s -o /dev/null -w "%{http_code} " -X POST https://api.<domain>/api/auth/login -H "content-type: application/json" -H "X-Forwarded-For: 10.0.0.$i" -d '{"email":"x@test.com","password":"nope-nope"}'; done`
Expected: fifteen `401` then `429`. The fake header did not give each request its own limit. Then check an API log line: the logged client address is yours, not `10.0.0.x` and not Caddy's.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "docs: server setup and deploy script"
```

---

### Task 6: Backups, monitoring and spend limits

**Who:** Nikhil

**Files:**
- Create: `deploy/backup.sh`, `frontend/src/app/privacy/page.tsx`, `frontend/src/app/terms/page.tsx`
- Modify: `docs/runbook.md`, `frontend/src/app/(auth)/signup/page.tsx`

**Interfaces:**
- Produces:
  - `deploy/backup.sh`: `pg_dump` from the postgres container, gzip, upload to R2 as `backups/<YYYY-MM-DD>.sql.gz`, exit non-zero on any failure. Run nightly at 02:00 UTC from the server's cron, with the result appended to a log file.
  - `docs/runbook.md` sections: deploy, roll back (check out the previous commit and run the deploy script), restore a backup, rotate a secret, what to do when the readiness check fails, where each log is.
  - An uptime monitor that requests `https://api.<domain>/api/health/ready` every 5 minutes and emails on failure.
  - Spend limits: a budget alert on the Google Cloud project for Gemini, a usage alert or a monthly check on the ElevenLabs account, and `BETA_SIGNUP_LIMIT` set.
  - A privacy page and a terms page linked from the sign-up page. The privacy page states: what is stored, that files are deleted after 7 days, that audio is sent to ElevenLabs for transcription and transcripts to Google for edit suggestions, and how to delete an account's data.

- [ ] **Step 1: Write and schedule the backup, then run it once by hand**

Run: `./deploy/backup.sh && echo done`
Expected: `done`, and the R2 bucket lists today's file under `backups/`.

- [ ] **Step 2: Restore drill**

On your Mac: download the backup, create a scratch database in the local Compose Postgres, restore into it, and count rows.
Run: `gunzip -c <file> | docker compose exec -T postgres psql -U app -d restore_test` then `SELECT count(*) FROM users;` and `SELECT count(*) FROM projects;`
Expected: the counts match production. Write the exact commands and the time taken in the runbook's restore section.

- [ ] **Step 3: Set up the uptime monitor and prove it alerts**

Stop the `redis` container on the server for 6 minutes.
Expected: `/api/health/ready` returns 503 with `"redis": "fail"`, the alert email arrives, ordinary API requests still work (the rate limiter fails open), and everything recovers when Redis is started again.

- [ ] **Step 4: Set the spend limits**

Before this step, read ElevenLabs' current data retention terms and Google's paid-tier data terms, and record the links and the date checked in the runbook. Then create the budget alert, note the ElevenLabs plan's included hours, and confirm `BETA_SIGNUP_LIMIT` in `.env.prod`.

- [ ] **Step 5: Write the privacy and terms pages and link them from sign-up.**

Run: `npm run lint && npm run build`
Expected: both succeed.

- [ ] **Step 6: Commit and deploy**

```bash
git add -A && git commit -m "feat: backups, runbook, privacy and terms pages" && ./deploy/deploy.sh
```

---

### Task 7: Launch drills and the README

**Who:** Nikhil

**Files:**
- Modify: `docs/benchmarks.md`, `docs/runbook.md`
- Create: `README.md`

**Interfaces:**
- Produces: measured numbers, three passed drills, and a README that presents the project.

- [ ] **Step 1: Load drill**

Upload three 10-minute videos at the same time from three browser tabs. Watch `docker stats` on the server.
Record in `docs/benchmarks.md`: time from upload complete to ready for review, render time, peak memory of the worker, and how long the third job waited in the queue.
Expected: all three finish, the API stays responsive during renders, and the server does not run out of memory. If memory peaks above 80%, lower worker concurrency to 1 or move to a larger server, and write down which.

- [ ] **Step 2: Reboot drill**

Start a render of a 10-minute video, then run `sudo reboot`.
Expected: after the reboot every container is back without manual action, and the project reaches `done` on its own. Record how long that took. A job whose worker was hard-killed is redelivered when Redis's visibility timeout (40 minutes) passes, so the wait can be that long. Write the measured time in the runbook.

- [ ] **Step 3: Deploy-during-render drill**

Start a render, then run `./deploy/deploy.sh`.
Expected: the worker is given up to 20 minutes to finish its current task before it is replaced, and the render completes. `stage_runs` shows either one successful render run, or an `interrupted` run followed by a successful one. Nothing is left `running`.

- [ ] **Step 4: Final checklist**

Confirm each line and tick it in the runbook:
- CI is green on the deployed commit.
- `nmap` shows only 22, 80 and 443.
- A backup from last night exists, and the restore drill is written down.
- The uptime monitor is active and has alerted once in a test.
- Gemini is on the paid tier with a budget alert. The ElevenLabs balance is known.
- `BETA_SIGNUP_LIMIT` is set. Privacy and terms pages are live.
- The eval results in `docs/evals.md` are from the deployed prompt and model.
- No `.env` file and no key is in the repository history.

- [ ] **Step 5: Write the README**

Sections: what it does (with a short screen recording or screenshots), the architecture diagram from the spec, the pipeline stages, the main engineering decisions with one line each (presigned multipart upload, idempotent stages with retry, word-index edit plans with validation and fallback, evals with numbers, rate limiting choice), the eval results table, the benchmark numbers, how to run it locally, and what is next (Stripe, transcript editing, chat edits).

- [ ] **Step 6: Commit and deploy**

```bash
git add -A && git commit -m "docs: README, benchmarks and launch checklist" && ./deploy/deploy.sh
```

---

## Done when

- The app is live at `https://app.<domain>` and a new user can go from sign-up to a downloaded edit.
- All three drills passed and their results are written down.
- Concepts Nikhil can explain: what a reverse proxy does and why TLS ends there, liveness versus readiness, why the worker and API are separate containers from one image, zero-secret repositories, what happens to in-flight jobs on deploy and on crash, backup versus restore-tested backup, and how the system would scale next (a second worker machine, a managed database, a CDN in front of downloads).
