# Milestone 3: Pipeline Skeleton Implementation Plan

> **How this plan is executed:** learning mode, not an autonomous agent run. One task at a time, in small steps, with a stop for review after each. Each task has a **Who** line: `Claude` writes boilerplate and UI; `Nikhil` writes interview-critical code from the signatures and tests here, or reviews Claude's version with a planted bug, as he chooses per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After an upload completes, four pipeline stages (probe, transcribe, plan, render) run as Celery jobs doing fake work, with live progress, cancel, automatic retries and manual retry from the failed stage.

**Architecture:** Stages 1 to 3 run one after another when the upload completes: each task enqueues the next one when it succeeds. Stage 4 runs when the user asks for a render. Every stage goes through one `run_stage` wrapper that records a `stage_runs` row, skips work already done, checks a cancel flag and classifies failures. The fake work is replaced by real work in Milestones 4 to 6 without touching the wrapper.

**Tech Stack:** Celery 5.6 with Redis as broker, a synchronous SQLAlchemy session on psycopg for workers, redis-py, Server-Sent Events from FastAPI, fakeredis in tests. Builds on Milestones 1 and 2.

**Spec:** `docs/superpowers/specs/2026-10-04-snipwise-design.md`

## Global Constraints

- All earlier constraints still apply.
- The API commits its database transaction **before** it enqueues a job. A worker can start before an uncommitted row is visible.
- Stages are idempotent: output keys are fixed, and a stage whose latest run succeeded does nothing when called again.
- Temporary errors retry up to 3 times with exponential backoff and jitter. Permanent errors (`PermanentStageError`) never retry.
- Celery settings: `task_acks_late=True`, `task_reject_on_worker_lost=True`, `worker_prefetch_multiplier=1`, `broker_transport_options={"visibility_timeout": 2400}` (must be longer than `task_time_limit`, or Redis hands a still-running job to a second worker; it is also how long a job waits after its whole worker is hard-killed), `task_soft_time_limit=1800`, `task_time_limit=2100`, results ignored. Workers run with `--concurrency=2`.
- Redis keys: `progress:{project_id}` holds JSON `{"stage": str, "percent": int}`; `cancel:{project_id}` holds `"1"`. Both expire after 3600 seconds.
- Render output key: `renders/{render_id}.mp4`. Download links last 5 minutes.
- Segment JSON shape, used from here on: `{"start": float, "end": float, "action": "keep" | "drop", "reason": null | "silence" | "filler" | "retake" | "user"}`.

## Review Focus

1. A worker is killed mid-stage: the job is redelivered, the stage runs again, and no `stage_runs` row is left as `running` forever (Task 2).
2. Cancel is pressed after the pipeline already finished: nothing breaks, and the next run is not cancelled by a stale flag (Tasks 2 and 3).
3. "Process" or "Render" is clicked twice at the same moment: one request wins, the other gets 409 (Task 3).
4. The project is deleted while it is processing: the remaining stages stop instead of failing loudly (Task 2).
5. The browser closes the progress stream: the server stops its loop and holds no connection open (Task 4).

## File Structure

```
backend/src/
  celery_app.py          Celery instance and settings
  database_sync.py       sync engine + SyncSessionLocal for workers
  redis_client.py        get_redis_sync(), get_redis_async()
  transcripts/models.py  Transcript
  edit_plans/models.py   EditPlan
  renders/models.py      Render, RenderStatus
  renders/schemas.py  renders/router.py
  pipeline/
    models.py      StageRun, Stage, StageStatus
    errors.py      PermanentStageError, StageCancelled
    progress.py    progress + cancel flags in Redis
    runner.py      run_stage, StageContext
    fake_work.py   the fake stage bodies for this milestone
    tasks.py       probe_task, transcribe_task, plan_task, render_task
    service.py     start_pipeline, start_render
    router.py      process, cancel, events (SSE)
    schemas.py
frontend/src/
  lib/events.ts
  app/(app)/projects/[id]/page.tsx   processing view, result view
```

---

### Task 1: Celery, the worker database session, Redis clients and the four new tables

**Who:** Claude

**Files:**
- Create: `backend/src/celery_app.py`, `backend/src/database_sync.py`, `backend/src/redis_client.py`
- Create: `backend/src/transcripts/{__init__,models}.py`, `backend/src/edit_plans/{__init__,models}.py`, `backend/src/renders/{__init__,models}.py`, `backend/src/pipeline/{__init__,models}.py`
- Create: `backend/alembic/versions/<rev>_pipeline_tables.py`
- Modify: `backend/alembic/env.py`, `backend/tests/conftest.py`
- Test: `backend/tests/pipeline/test_infra.py`

**Interfaces:**
- Produces:
  - `celery_app.celery_app`: `Celery("snipwise")` with the settings in Global Constraints, `include=["src.pipeline.tasks"]`.
  - `database_sync`: `sync_engine` (URL = `settings.database_url` with `+asyncpg` replaced by `+psycopg`), `SyncSessionLocal = sessionmaker(sync_engine, expire_on_commit=False)`.
  - `redis_client`: `get_redis_sync() -> redis.Redis`, `get_redis_async() -> redis.asyncio.Redis`, both `decode_responses=True`, each one cached instance.
  - Models (all with `id` UUID v7 and `created_at`):
    - `Transcript` (`transcripts`): `project_id` (fk, **unique**, ON DELETE CASCADE), `language: str`, `model: str`, `audio_seconds: float`, `words: JSONB`.
    - `EditPlan` (`edit_plans`): `project_id` (fk cascade), `version: int`, `created_by: str` (`"ai"` or `"user"`), `segments: JSONB`, `fallback_used: bool = False`, `fallback_reason: str | None`, `llm_model: str | None`, `input_tokens: int = 0`, `output_tokens: int = 0`. Unique `(project_id, version)`.
    - `Render` (`renders`): `project_id` (fk cascade), `edit_plan_id` (fk), `status: RenderStatus` (`pending, running, done, failed, cancelled`), `output_key: str | None`, `duration_sec: float | None`, `size_bytes: int | None`.
    - `StageRun` (`stage_runs`): `project_id` (fk cascade, indexed), `render_id` (fk, nullable), `stage: Stage` (`probe, transcribe, plan, render`), `status: StageStatus` (`running, succeeded, failed, cancelled`), `attempt: int`, `error_message: str | None`, `started_at`, `finished_at | None`.
  - Test setup in `conftest.py`: `celery_app.conf.update(task_always_eager=True, task_eager_propagates=False)` (a failed task must not raise inside the API call that enqueued it); `get_redis_sync` and `get_redis_async` patched to `fakeredis` instances that share one `FakeServer`, flushed after each test; a `sync_db` fixture giving a `SyncSessionLocal()` session.

- [ ] **Step 1: Add dependencies**

Run: `uv add "celery[redis]" redis "psycopg[binary]"` and `uv add --dev fakeredis`
Expected: resolves on Python 3.14. If `psycopg[binary]` has no 3.14 wheel, use `uv add psycopg` plus `brew install libpq`.

- [ ] **Step 2: Write the failing tests**

```python
# tests/pipeline/test_infra.py
def test_celery_is_configured_for_safe_redelivery():
    c = celery_app.conf
    assert c.task_acks_late is True and c.task_reject_on_worker_lost is True
    assert c.worker_prefetch_multiplier == 1
    assert c.broker_transport_options["visibility_timeout"] > c.task_time_limit

def test_sync_session_sees_async_committed_rows(sync_db, project):     # `project` was inserted by the async fixture
    assert sync_db.get(Project, project.id) is not None

def test_edit_plan_version_is_unique_per_project(sync_db, project):
    sync_db.add_all([EditPlan(project_id=project.id, version=1, created_by="ai", segments=[]),
                     EditPlan(project_id=project.id, version=1, created_by="user", segments=[])])
    with pytest.raises(IntegrityError):
        sync_db.commit()
```

- [ ] **Step 3: Run to see them fail**

Run: `uv run pytest tests/pipeline/test_infra.py -v`
Expected: FAIL, modules not found.

- [ ] **Step 4: Write the three infrastructure modules and the four models, then migrate**

Run: `uv run alembic revision --autogenerate -m "pipeline tables" && uv run alembic upgrade head`

- [ ] **Step 5: Run the tests, then start a real worker once**

Run: `uv run pytest -v`
Expected: all passed.
Run: `uv run celery -A src.celery_app worker --concurrency=2 --loglevel=info`
Expected: the banner shows `transport: redis://localhost:6379/0` and `concurrency: 2`, then "ready". Stop it with Ctrl+C.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: celery app, worker db session, pipeline tables"
```

---

### Task 2: The stage runner, progress and cancel

**Who:** Nikhil (the core of the pipeline: retries, idempotency, cancel)

**Files:**
- Create: `backend/src/pipeline/{errors,progress,runner}.py`
- Test: `backend/tests/pipeline/test_progress.py`, `backend/tests/pipeline/test_runner.py`

**Interfaces:**
- Consumes: `StageRun`, `Stage`, `StageStatus`, `Project`, `ProjectStatus`, `get_redis_sync`.
- Produces:
  - `pipeline.errors`: `class PermanentStageError(Exception)` (its message is shown to the user), `class StageCancelled(Exception)`.
  - `pipeline.progress` (sync, used by workers; the API reads the same keys with the async client):
    - `set_progress(project_id: UUID, stage: Stage, percent: int) -> None` (clamps to 0..100)
    - `get_progress(project_id: UUID) -> dict | None`
    - `clear_progress(project_id: UUID) -> None`
    - `request_cancel(project_id: UUID) -> None`, `is_cancelled(project_id: UUID) -> bool`, `clear_cancel(project_id: UUID) -> None`
  - `pipeline.runner`:
    ```python
    @dataclass
    class StageContext:
        session: Session
        project: Project
        stage: Stage
        render_id: UUID | None
        def report(self, percent: int) -> None: ...        # set_progress + check_cancelled
        def check_cancelled(self) -> None: ...             # raises StageCancelled if the flag is set or the project is deleted

    def run_stage(project_id: UUID, stage: Stage, work: Callable[[StageContext], None], *, render_id: UUID | None = None, final_attempt: bool = False) -> None
    ```
    Behaviour of `run_stage`, in order:
    1. Open a `SyncSessionLocal` session. Load the project. If it is missing or `deleted_at` is set, return silently.
    2. If the latest `StageRun` for `(project_id, stage, render_id)` is `succeeded`, return (skip).
    3. Mark any older `running` rows for the same `(project_id, stage, render_id)` as `failed` with `error_message="interrupted"`.
    4. Insert a `StageRun` with `status=running`, `attempt = previous attempts + 1`. Commit. Call `set_progress(project_id, stage, 0)`.
    5. Call `ctx.check_cancelled()`, then `work(ctx)`.
    6. On success: run is `succeeded`, `finished_at` set, commit.
    7. On `StageCancelled`: roll back, run is `cancelled`; project status → `cancelled` (guarded from `processing` or `rendering`); the `Render` row (if any) → `cancelled`; clear the flag and the progress key; commit; re-raise.
    8. On `PermanentStageError`: roll back, run is `failed` with the error's message; project → `failed`; render → `failed`; commit; re-raise.
    9. On any other exception: roll back, run is `failed` with message `"Something went wrong. Please try again."`; if `final_attempt` then project and render → `failed`; commit; re-raise so Celery can retry.

- [ ] **Step 1: Write the failing tests**

```python
# tests/pipeline/test_progress.py
def test_progress_round_trip_and_clamp(project):
    set_progress(project.id, Stage.transcribe, 140)
    assert get_progress(project.id) == {"stage": "transcribe", "percent": 100}
    clear_progress(project.id)
    assert get_progress(project.id) is None

def test_cancel_flag(project):
    assert not is_cancelled(project.id)
    request_cancel(project.id); assert is_cancelled(project.id)
    clear_cancel(project.id);   assert not is_cancelled(project.id)
```

```python
# tests/pipeline/test_runner.py        (`processing_project`: a project row with status "processing")
def runs(sync_db, project_id):
    return sync_db.scalars(select(StageRun).where(StageRun.project_id == project_id).order_by(StageRun.attempt)).all()

def test_success_records_one_succeeded_run(sync_db, processing_project):
    run_stage(processing_project.id, Stage.probe, lambda ctx: ctx.report(50))
    [r] = runs(sync_db, processing_project.id)
    assert (r.status, r.attempt, r.finished_at is not None) == (StageStatus.succeeded, 1, True)

def test_already_succeeded_stage_is_skipped(sync_db, processing_project):
    calls = []
    for _ in range(2):
        run_stage(processing_project.id, Stage.probe, lambda ctx: calls.append(1))
    assert len(calls) == 1 and len(runs(sync_db, processing_project.id)) == 1

def test_permanent_error_fails_the_project_with_its_message(sync_db, processing_project):
    def work(ctx): raise PermanentStageError("This video has no audio track.")
    with pytest.raises(PermanentStageError):
        run_stage(processing_project.id, Stage.probe, work)
    assert runs(sync_db, processing_project.id)[0].error_message == "This video has no audio track."
    assert sync_db.get(Project, processing_project.id).status == ProjectStatus.failed

def test_temporary_error_keeps_project_processing_until_final_attempt(sync_db, processing_project):
    def work(ctx): raise RuntimeError("boom: secret detail")
    with pytest.raises(RuntimeError):
        run_stage(processing_project.id, Stage.plan, work)
    sync_db.expire_all()
    assert sync_db.get(Project, processing_project.id).status == ProjectStatus.processing
    with pytest.raises(RuntimeError):
        run_stage(processing_project.id, Stage.plan, work, final_attempt=True)
    sync_db.expire_all()
    assert sync_db.get(Project, processing_project.id).status == ProjectStatus.failed
    r = runs(sync_db, processing_project.id)
    assert [x.attempt for x in r] == [1, 2] and "secret" not in r[1].error_message

def test_cancel_stops_the_stage_and_clears_the_flag(sync_db, processing_project):
    def work(ctx):
        request_cancel(ctx.project.id)
        ctx.report(10)                      # must raise StageCancelled
        raise AssertionError("not reached")
    with pytest.raises(StageCancelled):
        run_stage(processing_project.id, Stage.transcribe, work)
    sync_db.expire_all()
    assert sync_db.get(Project, processing_project.id).status == ProjectStatus.cancelled
    assert runs(sync_db, processing_project.id)[0].status == StageStatus.cancelled
    assert not is_cancelled(processing_project.id) and get_progress(processing_project.id) is None

def test_interrupted_run_is_closed_when_the_stage_restarts(sync_db, processing_project):
    sync_db.add(StageRun(project_id=processing_project.id, stage=Stage.probe, status=StageStatus.running, attempt=1)); sync_db.commit()
    run_stage(processing_project.id, Stage.probe, lambda ctx: None)
    r = runs(sync_db, processing_project.id)
    assert [(x.attempt, x.status, x.error_message) for x in r] == [(1, StageStatus.failed, "interrupted"), (2, StageStatus.succeeded, None)]

def test_deleted_project_is_ignored(sync_db, processing_project):
    processing_project.deleted_at = datetime.now(UTC); sync_db.merge(processing_project); sync_db.commit()
    calls = []
    run_stage(processing_project.id, Stage.probe, lambda ctx: calls.append(1))
    assert calls == [] and runs(sync_db, processing_project.id) == []

def test_work_that_wrote_to_the_db_is_rolled_back_on_failure(sync_db, processing_project):
    def work(ctx):
        ctx.project.title = "changed"; ctx.session.flush()
        raise RuntimeError("boom")
    with pytest.raises(RuntimeError):
        run_stage(processing_project.id, Stage.plan, work)
    sync_db.expire_all()
    assert sync_db.get(Project, processing_project.id).title != "changed"
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/pipeline/test_progress.py tests/pipeline/test_runner.py -v`
Expected: FAIL, modules not found.

- [ ] **Step 3: Write `errors.py` and `progress.py`.**

- [ ] **Step 4: Write `runner.py`** following the nine numbered rules. Status changes on the project use a guarded `UPDATE ... WHERE status IN ('processing','rendering')`.

- [ ] **Step 5: Run the tests to see them pass**

Run: `uv run pytest tests/pipeline -v`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: stage runner with skip, retry classification and cancel"
```

---

### Task 3: Tasks with fake work, and the process, cancel and render endpoints

**Who:** Nikhil

**Files:**
- Create: `backend/src/pipeline/{fake_work,tasks,service,schemas,router}.py`
- Create: `backend/src/renders/{schemas,router}.py`
- Modify: `backend/src/uploads/service.py` (start the pipeline on complete), `backend/src/config.py`, `backend/src/main.py`
- Test: `backend/tests/pipeline/test_pipeline_api.py`

**Interfaces:**
- Consumes: `run_stage`, `StageContext`, `transition`, `get_storage`, `request_cancel`, `clear_cancel`.
- Produces:
  - Settings: `fake_stage_seconds: float = 3.0`, `fake_fail_stage: str | None = None`, `fake_fail_times: int = 1`.
  - `pipeline.fake_work`: `fake_probe(ctx)`, `fake_transcribe(ctx)`, `fake_plan(ctx)`, `fake_render(ctx)`. Each loops 10 times: `ctx.report(i * 10)` then sleeps `fake_stage_seconds / 10`. If `fake_fail_stage == ctx.stage`, it raises `RuntimeError` the first `fake_fail_times` times (counted in Redis key `fakefail:{project_id}:{stage}`). In addition:
    - `fake_probe` sets `duration_sec=60.0, width=1280, height=720, fps=30.0` on the project.
    - `fake_transcribe` upserts a `Transcript` (`language="en"`, `model="fake"`, `audio_seconds=60.0`, `words=[]`).
    - `fake_plan` inserts `EditPlan(version=1, created_by="ai", segments=[{"start": 0.0, "end": 60.0, "action": "keep", "reason": None}])` if the project has no plan.
    - `fake_render` copies the source object to `renders/{render_id}.mp4` (download then upload), and sets the render's `output_key`, `duration_sec=60.0`, `size_bytes`.
  - `pipeline.tasks` (each `@celery_app.task(bind=True, autoretry_for=(Exception,), dont_autoretry_for=(PermanentStageError, StageCancelled), retry_backoff=2, retry_backoff_max=60, retry_jitter=True, max_retries=3)`):
    - `probe_task(self, project_id: str)`, `transcribe_task(self, project_id: str)`, `plan_task(self, project_id: str)`, `render_task(self, render_id: str)`.
    - Each calls `run_stage(..., final_attempt=self.request.retries >= self.max_retries)`.
    - `probe_task.max_retries == transcribe_task.max_retries == plan_task.max_retries == render_task.max_retries == 3`.
    - After `plan_task` succeeds: project `processing → ready_for_review`, progress key cleared.
    - After `render_task` succeeds: render `done`, project `rendering → done`, progress key cleared.
    - `STAGE_WORK: dict[Stage, Callable[[StageContext], None]]` maps each stage to its work function. This milestone maps to the fakes; later milestones swap entries.
  - `pipeline.service`:
    - `start_pipeline(project_id: UUID) -> None`: `clear_cancel`, then `probe_task.delay(str(project_id))`. The pipeline is a hand-off, not a Celery `chain`: `probe_task` ends with `transcribe_task.delay(project_id)`, and `transcribe_task` ends with `plan_task.delay(project_id)`, each only after its stage succeeded. A skipped (already succeeded) stage still hands off, which is what makes manual retry resume.
    - `start_render(render_id: UUID, project_id: UUID) -> None`: `clear_cancel`, then `render_task.delay(str(render_id))`.
  - Upload complete now also runs `transition(to=processing, from_=[uploaded])`, commits, then calls `start_pipeline`.
  - `POST /api/projects/{id}/process` → 202 `ProjectOut`. `transition(to=processing, from_=[failed, cancelled])`; `False` → 409 `invalid_state`. Commit, then `start_pipeline`.
  - `POST /api/projects/{id}/cancel` → 202. Status must be `processing` or `rendering`, else 409 `invalid_state`. Sets the cancel flag.
  - `POST /api/projects/{id}/renders` → 201 `RenderOut`. Requires at least one edit plan, else 409 `invalid_state`. `transition(to=rendering, from_=[ready_for_review, failed, cancelled])`; `False` → 409. Inserts a `Render` (`status=pending`, `edit_plan_id` = latest version). Commit, then `start_render`.
  - `GET /api/projects/{id}/renders/{render_id}` → `RenderOut`; `downloadUrl` is a 5-minute presigned link with filename `"{project.title}.mp4"` when `status == done`, else `null`. A render of another project → 404.
  - `renders.schemas.RenderOut(id, status, edit_plan_version, duration_sec, size_bytes, download_url, created_at)`.

- [ ] **Step 1: Write the failing tests**

Tests run eagerly, so the whole chain finishes inside the `complete` call. Set `fake_stage_seconds=0` in a fixture.

```python
# tests/pipeline/test_pipeline_api.py        (`uploaded_project`: helper that runs the M2 happy path and returns the project JSON)
async def test_upload_complete_runs_three_stages(client, user_headers, uploaded_project, sync_db):
    assert uploaded_project["status"] == "ready_for_review"
    stages = [(r.stage, r.status) for r in runs(sync_db, uploaded_project["id"])]
    assert stages == [("probe", "succeeded"), ("transcribe", "succeeded"), ("plan", "succeeded")]

async def test_render_then_download(client, user_headers, uploaded_project):
    pid = uploaded_project["id"]
    r = await client.post(f"/api/projects/{pid}/renders", headers=user_headers)
    assert r.status_code == 201
    got = (await client.get(f"/api/projects/{pid}/renders/{r.json()['id']}", headers=user_headers)).json()
    assert got["status"] == "done" and f"renders/{got['id']}.mp4" in got["downloadUrl"]
    assert (await client.get(f"/api/projects/{pid}", headers=user_headers)).json()["status"] == "done"

async def test_temporary_failure_is_retried_and_recovers(client, user_headers, settings_override, upload_and_complete, sync_db):
    settings_override(fake_fail_stage="transcribe", fake_fail_times=2)
    project = await upload_and_complete()
    assert project["status"] == "ready_for_review"
    attempts = [r.attempt for r in runs(sync_db, project["id"]) if r.stage == "transcribe"]
    assert attempts == [1, 2, 3]

async def test_failure_after_all_retries_then_manual_retry_resumes(client, user_headers, settings_override, upload_and_complete, sync_db):
    settings_override(fake_fail_stage="plan", fake_fail_times=99)
    project = await upload_and_complete()
    pid = project["id"]
    assert (await client.get(f"/api/projects/{pid}", headers=user_headers)).json()["status"] == "failed"
    settings_override(fake_fail_stage=None)
    res = await client.post(f"/api/projects/{pid}/process", headers=user_headers)
    assert res.status_code == 202
    assert (await client.get(f"/api/projects/{pid}", headers=user_headers)).json()["status"] == "ready_for_review"
    probe_runs = [r for r in runs(sync_db, pid) if r.stage == "probe"]
    assert len(probe_runs) == 1                       # probe was skipped on the retry

async def test_process_on_a_healthy_project_is_409(client, user_headers, uploaded_project):
    res = await client.post(f"/api/projects/{uploaded_project['id']}/process", headers=user_headers)
    assert res.status_code == 409 and res.json()["code"] == "invalid_state"

async def test_render_twice_second_is_409_while_first_runs(client, user_headers, uploaded_project, monkeypatch):
    monkeypatch.setattr("src.pipeline.service.start_render", lambda *a: None)   # leave the first render "running"
    pid = uploaded_project["id"]
    assert (await client.post(f"/api/projects/{pid}/renders", headers=user_headers)).status_code == 201
    assert (await client.post(f"/api/projects/{pid}/renders", headers=user_headers)).status_code == 409

async def test_cancel_only_while_active(client, user_headers, uploaded_project):
    res = await client.post(f"/api/projects/{uploaded_project['id']}/cancel", headers=user_headers)
    assert res.status_code == 409
    assert not is_cancelled(UUID(uploaded_project["id"]))        # no stale flag left behind

async def test_stale_cancel_flag_does_not_kill_the_next_run(client, user_headers, settings_override, upload_and_complete):
    ...  # fail the plan stage, set the cancel flag by hand, POST /process → ends ready_for_review

async def test_other_user_gets_404_on_all_pipeline_routes(client, other_headers, uploaded_project):
    pid = uploaded_project["id"]
    for path in ("process", "cancel", "renders"):
        assert (await client.post(f"/api/projects/{pid}/{path}", headers=other_headers)).status_code == 404
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/pipeline/test_pipeline_api.py -v`
Expected: FAIL.

- [ ] **Step 3: Write `fake_work.py` and `tasks.py`.** If the installed Celery version handles retries differently in eager mode and a retry test fails for that reason, change the test setup in `conftest.py`, not the task code; Step 6 checks real retry behaviour with a real worker.

- [ ] **Step 4: Write `service.py`, the two routers and schemas, and hook upload complete.**

- [ ] **Step 5: Run the tests to see them pass**

Run: `uv run pytest -v`
Expected: all passed.

- [ ] **Step 6: Check real redelivery by hand**

Set `FAKE_STAGE_SECONDS=20` in `.env`. Start the API and a worker, and note the worker's main process id from its banner. Upload a video. While the worker log shows the transcribe stage, kill the worker's child processes (the ones running tasks) with `pkill -9 -P <main pid>`.
Expected: the main process logs a lost worker, the job is put back on the queue (`task_reject_on_worker_lost`), a new child runs the transcribe stage again, `stage_runs` has attempt 1 as `failed / interrupted` and attempt 2 as `succeeded`, and the project reaches `ready_for_review`.
Know the other case too: if the **main** process is hard-killed, nothing can put the job back, so Redis redelivers it only when the visibility timeout (40 minutes) passes. Milestone 7 tests that case with a reboot.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: pipeline tasks with fake work, process, cancel and render endpoints"
```

---

### Task 4: Live progress over Server-Sent Events

**Who:** Nikhil

**Files:**
- Modify: `backend/src/pipeline/router.py`, `backend/src/pipeline/schemas.py`
- Test: `backend/tests/pipeline/test_events.py`

**Interfaces:**
- Consumes: `OwnedProject`, `get_redis_async`, `StageRun`.
- Produces:
  - `GET /api/projects/{id}/events` → `text/event-stream` (`StreamingResponse`, headers `Cache-Control: no-cache`, `X-Accel-Buffering: no`).
  - One event immediately, then one per second while the status is `processing` or `rendering`. The stream closes after it sends an event with any other status.
  - Each event is `data: <json>\n\n` with `{"status": str, "stage": str | null, "percent": int | null, "error": str | null}`. `stage` and `percent` come from the Redis progress key. `error` is the `error_message` of the latest failed `StageRun` when the status is `failed`, else `null`.
  - The loop uses a fresh database session per tick, and stops when `await request.is_disconnected()` is true.
  - `pipeline.schemas.ProgressEvent`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/pipeline/test_events.py
async def read_events(client, pid, headers):
    async with client.stream("GET", f"/api/projects/{pid}/events", headers=headers) as res:
        assert res.headers["content-type"].startswith("text/event-stream")
        return [json.loads(line[6:]) async for line in res.aiter_lines() if line.startswith("data: ")]

async def test_finished_project_sends_one_event_and_closes(client, user_headers, uploaded_project):
    events = await read_events(client, uploaded_project["id"], user_headers)
    assert events == [{"status": "ready_for_review", "stage": None, "percent": None, "error": None}]

async def test_active_project_streams_progress_until_done(client, user_headers, db, processing_project):
    set_progress(processing_project.id, Stage.transcribe, 40)
    async def finish():
        await asyncio.sleep(1.5)
        ...  # set the project status to ready_for_review and commit
    task = asyncio.create_task(finish())
    events = await read_events(client, str(processing_project.id), user_headers)
    await task
    assert events[0] == {"status": "processing", "stage": "transcribe", "percent": 40, "error": None}
    assert events[-1]["status"] == "ready_for_review" and len(events) >= 2

async def test_failed_project_reports_the_stage_error(client, user_headers, failed_project):   # has a failed StageRun "This video has no audio track."
    [event] = await read_events(client, str(failed_project.id), user_headers)
    assert event["status"] == "failed" and event["error"] == "This video has no audio track."

async def test_events_for_another_users_project_is_404(client, other_headers, uploaded_project):
    assert (await client.get(f"/api/projects/{uploaded_project['id']}/events", headers=other_headers)).status_code == 404
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/pipeline/test_events.py -v`
Expected: FAIL with 404.

- [ ] **Step 3: Write the endpoint** as an async generator wrapped in `StreamingResponse`.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest -v`
Expected: all passed.

- [ ] **Step 5: Check disconnect handling by hand**

With `FAKE_STAGE_SECONDS=20`, run `curl -N -H "Authorization: Bearer <token>" http://localhost:8000/api/projects/<id>/events`, watch two events arrive, press Ctrl+C.
Expected: the API log shows the request ending within about a second, and no further database queries for that stream.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: live pipeline progress over SSE"
```

---

### Task 5: Frontend processing and result views

**Who:** Claude

**Files:**
- Create: `frontend/src/lib/events.ts`
- Modify: `frontend/src/app/(app)/projects/[id]/page.tsx`

**Interfaces:**
- Consumes: `GET /events`, `POST /process`, `POST /cancel`, `POST /renders`, `GET /renders/{id}`.
- Produces:
  - `events.ts`: `subscribeToProject(projectId: string, onEvent: (e: ProgressEvent) => void): () => void` using `@microsoft/fetch-event-source` so the `Authorization` header can be sent (the browser's built-in `EventSource` cannot send headers). On a 401 it refreshes the token once and reconnects. Returns an unsubscribe function.
  - Project page, by status:
    - `processing` / `rendering`: three (or one) labelled steps, "Checking video", "Transcribing", "Planning edits" / "Rendering", with the active step's percentage, and a Cancel button.
    - `ready_for_review`: a Render button (the review screen arrives in Milestone 5).
    - `done`: a video player on the download URL, a Download button, and Edit again.
    - `failed`: the error message and a Retry button (`POST /process`, or `POST /renders` if an edit plan exists).
    - `cancelled`: "Cancelled" and the same Retry button.

- [ ] **Step 1: Run `npm install @microsoft/fetch-event-source` and write `events.ts`.**

- [ ] **Step 2: Write the status views.**

- [ ] **Step 3: Verify the build**

Run: `npm run lint && npm run build`
Expected: both succeed.

- [ ] **Step 4: Verify in the browser**

With `FAKE_STAGE_SECONDS=10`:
1. Upload a video: the three steps advance with percentages, then the Render button appears.
2. Press Render: progress shows, then the player plays the (unchanged) video and Download works.
3. Upload again and press Cancel mid-stage: the page shows "Cancelled"; Retry finishes the run.
4. Set `FAKE_FAIL_STAGE=plan` and `FAKE_FAIL_TIMES=99`, restart the worker, upload: the page shows the failure message and Retry. Unset the variables, restart the worker, press Retry: it finishes and the worker log shows probe and transcribe being skipped.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: processing, result, cancel and retry views"
```

---

## Done when

- An uploaded video moves through all four fake stages with live progress, and cancel, automatic retry and manual retry all work in the browser.
- Killing a worker mid-stage does not lose the job.
- Concepts Nikhil can explain: why a queue instead of doing the work in the request, at-least-once delivery and why stages must be idempotent, `acks_late` and the visibility timeout, temporary versus permanent errors, backoff with jitter, why the API commits before enqueueing, how the guarded status update prevents double runs, and why SSE instead of polling or WebSockets.
