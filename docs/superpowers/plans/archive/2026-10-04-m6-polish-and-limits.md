# Milestone 6: Polish and Limits Implementation Plan

> **How this plan is executed:** learning mode, not an autonomous agent run. One task at a time, in small steps, with a stop for review after each. Each task has a **Who** line: `Claude` writes boilerplate and UI; `Nikhil` writes interview-critical code from the signatures and tests here, or reviews Claude's version with a planted bug, as he chooses per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Renders get jump-cut zooms, burned-in captions and colour correction, and the app gets its limits: rate limiting, a daily AI token cap, and automatic clean-up of old files and abandoned uploads.

**Architecture:** Zoom, colour and captions are extra steps in the existing ffmpeg filter graph. Rate limiting is a FastAPI dependency backed by one atomic Redis script. The token cap is a per-user daily counter in Redis checked by the plan stage. Clean-up runs as two daily Celery Beat jobs that are safe to run twice.

**Tech Stack:** ffmpeg with libass, Redis Lua scripts, Celery Beat. Builds on Milestones 1 to 5. This completes version 1.

**Spec:** `docs/superpowers/specs/2026-10-04-snipwise-design.md`

## Global Constraints

- All earlier constraints still apply.
- Zoom: every second kept segment (the 2nd, 4th, ...) is scaled to 108% and centre-cropped back to the original size. Output size never changes.
- Colour: one fixed preset, `eq=contrast=1.05:saturation=1.10`.
- Captions: one style. White bold text with a black outline, bottom centre, at most 5 words or 2.5 seconds per line. Font size is 6% of the video's short side.
- Filter order: cuts and zoom, then join, then colour, then captions. Captions are never zoomed or colour-shifted.
- Rate limits: 15 per minute per IP on `/api/auth/*`; 250 per minute per user on everything else; 10 per minute per user on `POST .../process` and `POST .../renders`; `sign-part` has its own limit of 1200 per minute per user and is not counted in the 250.
- A blocked request gets 429 `rate_limited` with a `Retry-After` header in seconds.
- If Redis is unreachable, the rate limiter lets the request through and logs a warning (fail open).
- Daily AI token cap: 200,000 tokens per user per UTC day. Over the cap, plans fall back to silence cuts only with `fallback_reason = "daily_ai_limit"`.
- Clean-up: multipart uploads older than 24 hours are aborted; a project's files are deleted when `files_expire_at` has passed. Projects that are `processing` or `rendering` are never expired.
- Scheduled jobs are idempotent and run in UTC.

## Review Focus

1. Caption text containing `{`, `}`, a backslash, emoji or non-Latin script does not break the subtitle file or the render (Task 2).
2. Redis goes down: API requests still succeed (Task 3).
3. A 2 GB upload makes about 256 `sign-part` calls in a short time: the upload is not cut off by the general limit (Task 3).
4. The expiry job runs twice in a row, or while a render is in progress: nothing is deleted twice and active work is untouched (Task 5).
5. A portrait video gets captions that fit the frame width (Task 2).

## File Structure

```
backend/src/
  renders/filter_graph.py    + zoom, colour, captions
  renders/captions.py        remap_words, group_lines, ass_escape, build_ass
  media/ffmpeg.py            + cwd parameter
  pipeline/stages/render.py  passes options, writes the caption file
  rate_limit/
    algorithms.py   five algorithms, one signature
    dependency.py   rate_limit() FastAPI dependency
  edit_plans/budget.py       daily token counter
  pipeline/stages/plan.py    checks the budget
  maintenance/tasks.py       abort_stale_uploads, expire_files
  storage/                   + list_multipart_uploads
  celery_app.py              + beat schedule
backend/scripts/compare_rate_limits.py
docs/rate-limiting.md
```

---

### Task 1: Jump-cut zooms and colour correction

**Who:** Nikhil

**Files:**
- Modify: `backend/src/renders/filter_graph.py`, `backend/src/pipeline/stages/render.py`
- Test: `backend/tests/renders/test_filter_graph.py`, `backend/tests/pipeline/test_real_pipeline.py`

**Interfaces:**
- Consumes: `RenderOptions(fps, width, height, zoom, color, captions_path)`, `build_filter_graph`.
- Produces:
  - With `opts.zoom`, the video chain of each keep at an odd position (index 1, 3, ...) gets `scale=trunc(iw*1.08/2)*2:trunc(ih*1.08/2)*2,crop=<W>:<H>` after `setpts`, where `W` and `H` are `opts.width` and `opts.height` rounded down to even numbers.
  - With `opts.color`, `eq=contrast=1.05:saturation=1.10` is applied to the joined video before `[vout]`.
  - `render_stage` sets `zoom=options.jump_cut_zoom` and `color=options.color_correction`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/renders/test_filter_graph.py
KEEPS = [TimeRange(0.0, 1.0), TimeRange(2.0, 3.0), TimeRange(4.0, 5.0)]

def test_zoom_is_applied_to_every_second_keep_only():
    g = build_filter_graph(KEEPS, RenderOptions(fps=30, width=640, height=360, zoom=True))
    assert g.count("crop=640:360") == 1 and g.count("scale=trunc(iw*1.08/2)*2:trunc(ih*1.08/2)*2") == 1

def test_single_keep_is_never_zoomed():
    g = build_filter_graph([TimeRange(0.0, 5.0)], RenderOptions(fps=30, width=640, height=360, zoom=True))
    assert "crop" not in g

def test_odd_dimensions_are_cropped_to_even():
    g = build_filter_graph(KEEPS, RenderOptions(fps=30, width=641, height=361, zoom=True))
    assert "crop=640:360" in g

def test_colour_comes_after_the_join():
    g = build_filter_graph(KEEPS, RenderOptions(fps=30, width=640, height=360, color=True))
    assert g.index("concat=") < g.index("eq=contrast=1.05:saturation=1.10") and g.rstrip().endswith("[vout]")

def test_plain_options_match_milestone_4_output():
    g = build_filter_graph(KEEPS, RenderOptions(fps=30, width=640, height=360))
    assert "crop" not in g and "eq=" not in g and "subtitles" not in g
```

```python
# tests/pipeline/test_real_pipeline.py
async def test_zoom_and_colour_keep_the_frame_size(client, user_headers, storage, upload_file, sample_video, tmp_path):
    FakeTranscriber.default_words = [Word("one", 0.1, 0.9), Word("two", 1.0, 1.9), Word("three", 5.1, 5.9), Word("four", 6.0, 6.9)]
    pid = (await upload_file(sample_video, options={"jumpCutZoom": True, "colorCorrection": True, "captions": False}))["id"]
    render = (await client.post(f"/api/projects/{pid}/renders", headers=user_headers)).json()
    out = tmp_path / "o.mp4"; storage.download_file(f"renders/{render['id']}.mp4", out)
    assert (probe(out).width, probe(out).height) == (640, 360)
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/renders/test_filter_graph.py -v`
Expected: the new tests FAIL, the Milestone 4 tests still pass.

- [ ] **Step 3: Extend `build_filter_graph` and `render_stage`.**

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/renders tests/pipeline/test_real_pipeline.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: jump-cut zooms and colour correction"
```

---

### Task 2: Captions

**Who:** Nikhil

**Files:**
- Create: `backend/src/renders/captions.py`
- Modify: `backend/src/renders/filter_graph.py`, `backend/src/renders/render.py`, `backend/src/media/ffmpeg.py`, `backend/src/pipeline/stages/render.py`
- Test: `backend/tests/renders/test_captions.py`, `backend/tests/pipeline/test_real_pipeline.py`

**Interfaces:**
- Consumes: `Word`, `TimeRange`, `RenderOptions`, `run_ffmpeg`.
- Produces:
  - `renders.captions`:
    ```python
    @dataclass(frozen=True)
    class CaptionLine:
        start: float; end: float; text: str

    def remap_words(words: list[Word], keeps: list[TimeRange]) -> list[Word]
    def group_lines(words: list[Word], *, max_words: int = 5, max_sec: float = 2.5, max_gap: float = 0.6) -> list[CaptionLine]
    def ass_escape(text: str) -> str
    def ass_time(seconds: float) -> str                    # "H:MM:SS.cc"
    def build_ass(lines: list[CaptionLine], width: int, height: int) -> str
    ```
    - `remap_words`: keeps only entries with `type == "word"` whose midpoint is inside a keep range. New time = (kept time before that range) + (time − range start), clamped to the range. Rounded to 3 decimals.
    - `group_lines`: starts a new line when the current one has `max_words` words, when adding the word would make the line longer than `max_sec`, or when the gap before the word is more than `max_gap`. A line ends at its last word's end. Line times are rounded to 3 decimals.
    - `ass_escape`: removes `{`, `}` and `\`, and turns any newline into a space.
    - `build_ass`: a full ASS file. `PlayResX = width`, `PlayResY = height`. One style `Default`: font `Noto Sans`, size `round(min(width, height) * 0.06)`, bold, primary colour white (`&H00FFFFFF`), outline black, outline width `max(2, round(min(width, height) * 0.004))`, alignment 2 (bottom centre), `MarginV = round(height * 0.08)`, `MarginL = MarginR = round(width * 0.06)`. One `Dialogue` line per caption line.
  - `run_ffmpeg(..., cwd: Path | None = None)`: runs ffmpeg in that directory.
  - With `opts.captions_path`, the graph applies `subtitles=<file name only>` as the last video filter, and `render_video` runs ffmpeg with `cwd` set to the file's directory (so no path needs escaping inside the filter).
  - `render_stage`: when `options.captions` is on, it loads the transcript, calls `remap_words`, `group_lines` and `build_ass`, writes `captions.ass` in the work directory and passes it as `captions_path`. No words → no caption file.

- [ ] **Step 1: Make sure ffmpeg has libass**

Run: `ffmpeg -hide_banner -filters | grep subtitles`
Expected: a line containing `subtitles`. If there is none (the standard Homebrew build), run `brew install ffmpeg-full` and set `FFMPEG_BIN` and `FFPROBE_BIN` in `.env` to `$(brew --prefix ffmpeg-full)/bin/ffmpeg` and `.../ffprobe`, then check again with that binary.

- [ ] **Step 2: Write the failing tests**

```python
# tests/renders/test_captions.py
KEEPS = [TimeRange(0.85, 2.15), TimeRange(4.85, 5.65)]

def test_remap_shifts_kept_words_and_drops_cut_ones():
    words = [Word("one", 1.0, 1.4), Word("two", 1.6, 2.0), Word("gone", 3.0, 3.4), Word("(laughs)", 5.0, 5.2, type="audio_event"), Word("three", 5.0, 5.5)]
    assert remap_words(words, KEEPS) == [Word("one", 0.15, 0.55), Word("two", 0.75, 1.15), Word("three", 1.45, 1.95)]

def test_word_straddling_a_cut_is_clamped():
    assert remap_words([Word("edge", 2.0, 2.2)], KEEPS) == [Word("edge", 1.15, 1.3)]

def test_lines_break_on_word_count_duration_and_gap():
    words = [Word(str(i), i * 0.3, i * 0.3 + 0.2) for i in range(7)] + [Word("late", 5.0, 5.3)]
    lines = group_lines(words)
    assert [l.text for l in lines] == ["0 1 2 3 4", "5 6", "late"]
    assert (lines[0].start, lines[0].end) == (0.0, 1.4)

def test_long_slow_line_breaks_on_duration():
    words = [Word("a", 0.0, 1.0), Word("b", 1.1, 2.0), Word("c", 2.1, 3.0)]
    assert [l.text for l in group_lines(words)] == ["a b", "c"]

def test_escape_and_time_format():
    assert ass_escape("hi {\\b1}there\nyou") == "hi b1there you"
    assert ass_time(1.45) == "0:00:01.45" and ass_time(3725.5) == "1:02:05.50"

def test_ass_file_scales_with_the_short_side():
    landscape = build_ass([CaptionLine(0.0, 1.0, "hello world")], 1920, 1080)
    portrait = build_ass([CaptionLine(0.0, 1.0, "नमस्ते 👋")], 1080, 1920)
    assert "PlayResX: 1920" in landscape and "PlayResY: 1080" in landscape
    assert ",65," in landscape.split("Style: Default,")[1] and ",65," in portrait.split("Style: Default,")[1]
    assert "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,hello world" in landscape
    assert "नमस्ते 👋" in portrait
```

```python
# tests/pipeline/test_real_pipeline.py
async def test_render_with_captions_succeeds(client, user_headers, storage, upload_file, sample_video):
    FakeTranscriber.default_words = [Word("one {x}", 0.1, 0.9), Word("नमस्ते", 1.0, 1.9), Word("three", 5.1, 5.9), Word("four", 6.0, 6.9)]
    pid = (await upload_file(sample_video, options={"captions": True}))["id"]
    render = (await client.post(f"/api/projects/{pid}/renders", headers=user_headers)).json()
    assert (await client.get(f"/api/projects/{pid}/renders/{render['id']}", headers=user_headers)).json()["status"] == "done"
```

- [ ] **Step 3: Run to see them fail**

Run: `uv run pytest tests/renders/test_captions.py -v`
Expected: FAIL, module not found.

- [ ] **Step 4: Write `captions.py`, add `cwd` to `run_ffmpeg`, extend the graph, `render_video` and `render_stage`.**

- [ ] **Step 5: Run the tests to see them pass**

Run: `uv run pytest tests/renders tests/pipeline/test_real_pipeline.py -v`
Expected: all passed.

- [ ] **Step 6: Look at real output**

Render one landscape and one portrait recording with captions on. Check: captions match the speech after cuts, they sit inside the frame on the portrait video, zoomed segments do not zoom the captions, and a clip with Hindi speech shows real glyphs and not boxes.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: burned-in captions"
```

---

### Task 3: Rate limiting

**Who:** Nikhil (he started this in the Node project; here he builds all five algorithms, compares them and picks one)

**Files:**
- Create: `backend/src/rate_limit/{__init__,algorithms,dependency}.py`, `backend/scripts/compare_rate_limits.py`, `docs/rate-limiting.md`
- Modify: `backend/src/exceptions.py` (headers on `AppError`), `backend/src/config.py`, every router file, `backend/tests/conftest.py`
- Test: `backend/tests/rate_limit/test_algorithms.py`, `backend/tests/rate_limit/test_dependency.py`

**Interfaces:**
- Consumes: `get_redis_async`, `CurrentUser`.
- Produces:
  - Settings: `rate_limit_enabled: bool = True` (tests set it to `False` except in `tests/rate_limit/`).
  - `AppError` gains an optional `headers: dict[str, str]` that the handler copies onto the response.
  - `rate_limit.algorithms`:
    ```python
    @dataclass(frozen=True)
    class RateLimitResult:
        allowed: bool; retry_after_sec: int          # 0 when allowed, at least 1 when blocked

    Algorithm = Callable[..., Awaitable[RateLimitResult]]
    async def fixed_window(redis, key: str, limit: int, window_sec: int, *, now: float | None = None) -> RateLimitResult
    async def sliding_log(redis, key, limit, window_sec, *, now=None) -> RateLimitResult
    async def sliding_counter(redis, key, limit, window_sec, *, now=None) -> RateLimitResult
    async def token_bucket(redis, key, limit, window_sec, *, now=None) -> RateLimitResult      # capacity = limit, refill = limit / window_sec per second
    async def leaky_bucket(redis, key, limit, window_sec, *, now=None) -> RateLimitResult       # capacity = limit, leak = limit / window_sec per second
    ```
    Each one is a single Lua script, so the read and the write are atomic. `now` defaults to `time.time()` and exists so tests can control the clock. Every key gets an expiry so idle keys disappear. `sliding_counter` allows a request when `current + previous * (share of the previous window still inside the last window_sec) < limit`.
  - `rate_limit.dependency`:
    ```python
    def rate_limit(name: str, limit: int, window_sec: int, *, by: Literal["ip", "user"]) -> Callable     # a FastAPI dependency
    ```
    Key: `rl:{name}:{client ip}` or `rl:{name}:{user id}`. Uses `sliding_counter` (change it here if the comparison in Step 6 says otherwise). Blocked → `RateLimited` (429, `rate_limited`, `"Too many requests. Try again in {n} seconds."`, header `Retry-After: {n}`). `redis.RedisError` → log a warning and allow. Does nothing when `rate_limit_enabled` is false.
  - Applied as router-level or route-level dependencies with the numbers from Global Constraints: `auth` (15/60, ip), `api` (250/60, user), `jobs` (10/60, user, on `POST process` and `POST renders` in addition to `api`), `sign` (1200/60, user, on `sign-part` instead of `api`).

- [ ] **Step 1: Write the failing tests**

These tests use the real Redis from Docker Compose on database 15, flushed before each test (Lua scripts need a real Redis).

```python
# tests/rate_limit/test_algorithms.py
ALGOS = [fixed_window, sliding_log, sliding_counter, token_bucket, leaky_bucket]

async def burst(algo, r, n, at):
    return sum([(await algo(r, "k", 5, 10, now=at)).allowed for _ in range(n)])

@pytest.mark.parametrize("algo", ALGOS)
async def test_allows_up_to_the_limit_then_blocks(algo, real_redis):
    assert await burst(algo, real_redis, 7, at=100.0) == 5
    blocked = await algo(real_redis, "k", 5, 10, now=100.0)
    assert not blocked.allowed and blocked.retry_after_sec >= 1

@pytest.mark.parametrize("algo", ALGOS)
async def test_recovers_fully_after_a_long_quiet_time(algo, real_redis):
    await burst(algo, real_redis, 5, at=100.0)
    assert await burst(algo, real_redis, 5, at=200.0) == 5

@pytest.mark.parametrize("algo,expected", [(fixed_window, 5), (sliding_log, 0), (sliding_counter, 1), (token_bucket, 0), (leaky_bucket, 0)])
async def test_burst_across_a_window_boundary(algo, expected, real_redis):
    await burst(algo, real_redis, 5, at=109.9)                     # end of the window that started at 100
    assert await burst(algo, real_redis, 5, at=110.1) == expected  # fixed window lets 10 through in 0.2 seconds

@pytest.mark.parametrize("algo", [token_bucket, leaky_bucket])
async def test_buckets_free_one_slot_every_two_seconds(algo, real_redis):
    await burst(algo, real_redis, 5, at=100.0)
    assert await burst(algo, real_redis, 3, at=102.1) == 1

@pytest.mark.parametrize("algo", ALGOS)
async def test_keys_expire(algo, real_redis):
    await algo(real_redis, "k", 5, 10, now=time.time())
    keys = await real_redis.keys("*")
    assert keys and all([await real_redis.ttl(k) > 0 for k in keys])

async def test_different_keys_do_not_share_a_limit(real_redis):
    await burst(sliding_counter, real_redis, 5, at=100.0)
    assert (await sliding_counter(real_redis, "other", 5, 10, now=100.0)).allowed
```

```python
# tests/rate_limit/test_dependency.py       (settings_override(rate_limit_enabled=True); the app's redis points at real_redis)
async def test_sixteenth_login_in_a_minute_is_429(client):
    codes = [(await client.post("/api/auth/login", json={"email": "x@test.com", "password": "nope-nope"})).status_code for _ in range(16)]
    assert codes[:15] == [401] * 15 and codes[15] == 429

async def test_429_has_the_error_shape_and_retry_after(client):
    for _ in range(15):
        await client.post("/api/auth/login", json={"email": "x@test.com", "password": "nope-nope"})
    res = await client.post("/api/auth/login", json={"email": "x@test.com", "password": "nope-nope"})
    assert res.json()["code"] == "rate_limited" and int(res.headers["retry-after"]) >= 1

async def test_users_have_separate_limits(client, user_headers, other_headers):
    for _ in range(250):
        await client.get("/api/projects", headers=user_headers)
    assert (await client.get("/api/projects", headers=user_headers)).status_code == 429
    assert (await client.get("/api/projects", headers=other_headers)).status_code == 200

async def test_sign_part_is_not_counted_in_the_general_limit(client, user_headers, started_upload):
    for n in range(300):
        res = await client.post(f"/api/projects/{started_upload['id']}/upload/sign-part", json={"partNumber": 1}, headers=user_headers)
        assert res.status_code == 200
    assert (await client.get("/api/projects", headers=user_headers)).status_code == 200

async def test_eleventh_render_request_in_a_minute_is_429(client, user_headers, uploaded_project):
    codes = [(await client.post(f"/api/projects/{uploaded_project['id']}/renders", headers=user_headers)).status_code for _ in range(11)]
    assert codes[10] == 429

async def test_redis_down_lets_requests_through(client, user_headers, monkeypatch):
    async def broken(*a, **k): raise redis.ConnectionError("down")
    monkeypatch.setattr("src.rate_limit.dependency.sliding_counter", broken)
    assert (await client.get("/api/projects", headers=user_headers)).status_code == 200
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/rate_limit -v`
Expected: FAIL, module not found.

- [ ] **Step 3: Write the five algorithms.** Start with `fixed_window` (the one from the Node project), then `sliding_log`, `sliding_counter`, `token_bucket`, `leaky_bucket`.

- [ ] **Step 4: Run the algorithm tests to see them pass**

Run: `uv run pytest tests/rate_limit/test_algorithms.py -v`
Expected: all passed.

- [ ] **Step 5: Write the dependency, add `headers` to `AppError`, and apply the limits to the routers.**

Run: `uv run pytest -v`
Expected: all passed.

- [ ] **Step 6: Compare and decide**

Write `scripts/compare_rate_limits.py`: for each algorithm, with limit 100 per 60 seconds and a simulated clock, run three scenarios and print one table: (a) steady 1 request per second for 5 minutes, (b) 100 requests at second 59 and 100 at second 61, (c) 10 requests per second for 2 minutes. Columns: requests allowed, largest number allowed in any 2-second span, Redis memory for the key (`MEMORY USAGE`).
Run: `uv run python scripts/compare_rate_limits.py`
Expected: fixed window allows 200 in scenario (b); sliding log uses the most memory.
Write the table into `docs/rate-limiting.md` with a short decision: which algorithm the app uses and why. The spec's default is the sliding window counter. If the decision differs, change the one line in `dependency.py`.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: rate limiting with five compared algorithms"
```

---

### Task 4: The daily AI token cap

**Who:** Nikhil

**Files:**
- Create: `backend/src/edit_plans/budget.py`
- Modify: `backend/src/pipeline/stages/plan.py`, `backend/src/config.py`
- Test: `backend/tests/edit_plans/test_budget.py`

**Interfaces:**
- Consumes: `get_redis_sync`, `make_plan`, `ProjectOptions`.
- Produces:
  - Setting: `daily_token_cap: int = 200_000`.
  - `edit_plans.budget`:
    ```python
    def tokens_used_today(user_id: UUID, *, today: date | None = None) -> int
    def add_tokens(user_id: UUID, count: int, *, today: date | None = None) -> None      # INCRBY, key expires after 172800 seconds
    def has_budget(user_id: UUID, *, today: date | None = None) -> bool                   # used < daily_token_cap
    ```
    Key: `tokens:{user_id}:{YYYY-MM-DD}` with the UTC date.
  - `plan_stage`: when an AI option is on and `has_budget` is false, it calls `make_plan` with a copy of the options that has `remove_fillers=False` and `keep_best_take=False`, and stores `fallback_used=True`, `fallback_reason="daily_ai_limit"`. After any plan, it calls `add_tokens(user_id, input_tokens + output_tokens)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/edit_plans/test_budget.py
def test_counter_is_per_user_and_per_utc_day():
    u1, u2 = uuid.uuid7(), uuid.uuid7()
    add_tokens(u1, 150, today=date(2026, 11, 1)); add_tokens(u1, 50, today=date(2026, 11, 1))
    assert tokens_used_today(u1, today=date(2026, 11, 1)) == 200
    assert tokens_used_today(u1, today=date(2026, 11, 2)) == 0
    assert tokens_used_today(u2, today=date(2026, 11, 1)) == 0

def test_counter_key_expires(redis_sync):
    u = uuid.uuid7(); add_tokens(u, 1, today=date(2026, 11, 1))
    assert 0 < redis_sync.ttl(f"tokens:{u}:2026-11-01") <= 172800

def test_plan_stage_records_usage(sync_db, transcribed):
    FakeLLM.responses = [[]]
    run_stage(transcribed.id, Stage.plan, plan_stage)
    assert tokens_used_today(transcribed.user_id) == 110

def test_over_the_cap_falls_back_without_calling_the_llm(sync_db, transcribed, settings_override):
    settings_override(daily_token_cap=100)
    add_tokens(transcribed.user_id, 100)
    run_stage(transcribed.id, Stage.plan, plan_stage)
    plan = sync_db.scalar(select(EditPlan).where(EditPlan.project_id == transcribed.id))
    assert (plan.fallback_used, plan.fallback_reason) == (True, "daily_ai_limit") and FakeLLM.calls == []
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/edit_plans/test_budget.py -v`
Expected: FAIL, module not found.

- [ ] **Step 3: Write `budget.py` and update `plan_stage`.**

- [ ] **Step 4: Run every test**

Run: `uv run pytest -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: daily AI token cap per user"
```

---

### Task 5: Scheduled clean-up

**Who:** Nikhil

**Files:**
- Create: `backend/src/maintenance/{__init__,tasks}.py`
- Modify: `backend/src/storage/{base,s3,memory}.py`, `backend/src/celery_app.py`, `backend/src/projects/status.py`
- Test: `backend/tests/maintenance/test_cleanup.py`

**Interfaces:**
- Consumes: `get_storage`, `SyncSessionLocal`, `Project`, `Render`.
- Produces:
  - `Storage.list_multipart_uploads() -> list[MultipartUploadInfo]` with `MultipartUploadInfo(key: str, upload_id: str, initiated_at: datetime)`. `MemoryStorage.create_multipart_upload` accepts an optional `initiated_at` for tests.
  - `projects.status.ALLOWED`: `expired` is added as an allowed target from `uploaded`, `ready_for_review`, `done`, `failed` and `cancelled`.
  - `maintenance.tasks`:
    - `abort_stale_uploads() -> int` (Celery task): aborts every multipart upload started more than 24 hours ago, sets `upload_id = NULL` on projects that referenced one, returns how many were aborted.
    - `expire_files() -> int` (Celery task): takes up to 100 projects where `files_expire_at < now()`, `deleted_at IS NULL` and status is not `processing`, `rendering` or `expired`. For each: `delete_prefix("projects/{id}/")`, `delete_object` for every render `output_key`, set those `output_key`s to `NULL`, and set the status to `expired` with a guarded update that repeats the status condition. Returns how many were expired.
  - `celery_app.conf.beat_schedule`: `abort_stale_uploads` at 03:00 UTC, `expire_files` at 03:15 UTC, `timezone = "UTC"`. Run with `uv run celery -A src.celery_app beat --loglevel=info`.
  - `GET /api/projects/{id}/renders/{render_id}` returns `downloadUrl: null` when the render's `output_key` is `NULL`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/maintenance/test_cleanup.py
def test_only_old_uploads_are_aborted(storage, sync_db, project):
    old = storage.create_multipart_upload("projects/a/source", "video/mp4", initiated_at=datetime.now(UTC) - timedelta(hours=25))
    new = storage.create_multipart_upload("projects/b/source", "video/mp4", initiated_at=datetime.now(UTC) - timedelta(hours=1))
    project.upload_id = old; sync_db.merge(project); sync_db.commit()
    assert abort_stale_uploads() == 1
    assert storage.active_upload_ids() == {new}
    sync_db.expire_all(); assert sync_db.get(Project, project.id).upload_id is None
    assert abort_stale_uploads() == 0

def test_expired_project_loses_its_files_and_changes_status(storage, sync_db, done_project):     # has source, audio.wav and one render object
    done_project.files_expire_at = datetime.now(UTC) - timedelta(days=1); sync_db.merge(done_project); sync_db.commit()
    assert expire_files() == 1
    sync_db.expire_all()
    assert sync_db.get(Project, done_project.id).status == ProjectStatus.expired
    assert storage.object_size(f"projects/{done_project.id}/source") is None
    render = sync_db.scalar(select(Render).where(Render.project_id == done_project.id))
    assert render.output_key is None and storage.all_keys() == []
    assert expire_files() == 0                                    # second run does nothing

def test_active_and_future_projects_are_left_alone(storage, sync_db, rendering_project, done_project):
    rendering_project.files_expire_at = datetime.now(UTC) - timedelta(days=1)
    done_project.files_expire_at = datetime.now(UTC) + timedelta(days=1)
    sync_db.merge(rendering_project); sync_db.merge(done_project); sync_db.commit()
    assert expire_files() == 0
    assert storage.object_size(f"projects/{rendering_project.id}/source") is not None

async def test_expired_project_in_the_api(client, user_headers, expired_project):
    pid = expired_project["id"]
    assert (await client.get(f"/api/projects/{pid}", headers=user_headers)).json()["status"] == "expired"
    assert (await client.post(f"/api/projects/{pid}/renders", headers=user_headers)).status_code == 409
    assert (await client.get(f"/api/projects/{pid}/source-url", headers=user_headers)).status_code == 409

def test_beat_schedule_has_both_jobs():
    names = {entry["task"] for entry in celery_app.conf.beat_schedule.values()}
    assert names == {"src.maintenance.tasks.abort_stale_uploads", "src.maintenance.tasks.expire_files"}
```

Add `all_keys()` to `MemoryStorage`.

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/maintenance -v`
Expected: FAIL, module not found.

- [ ] **Step 3: Add `list_multipart_uploads` to the three storage modules, write `maintenance/tasks.py`, add the schedule.**

- [ ] **Step 4: Run every test, including the storage integration test**

Run: `uv run pytest -v && uv run pytest tests/storage -m integration -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: scheduled clean-up of stale uploads and expired files"
```

---

### Task 6: Frontend polish

**Who:** Claude

**Files:**
- Modify: `frontend/src/lib/api.ts`, `frontend/src/app/(app)/dashboard/page.tsx`, `frontend/src/app/(app)/projects/[id]/page.tsx`, `frontend/src/app/(app)/projects/[id]/review.tsx`

**Interfaces:**
- Consumes: everything built so far.
- Produces:
  - `apiFetch` handles 429: it throws `ApiError` with the server's message, and the page shows it as a notice without logging the user out.
  - Dashboard cards show "Files deleted on 12 Nov" from `filesExpireAt`, and an "Expired" badge.
  - Project page gets an `expired` view: "This project's files were deleted after 7 days. Upload the video again to edit it."
  - Review header shows "You reached today's AI limit, so only silences were removed." when `fallbackReason` is `daily_ai_limit`.
  - The upload page blocks the upload with a clear message when `minutesUsed >= minutesLimit`.

- [ ] **Step 1: Make the changes.**

- [ ] **Step 2: Verify the build**

Run: `npm run lint && npm run build`
Expected: both succeed.

- [ ] **Step 3: Full walk-through in the browser**

With real Scribe and Gemini keys, record a 2-minute clip with retakes, fillers and pauses and take it through the whole flow: upload, watch progress, review, flip two segments, render with zooms, captions and colour, download, edit again. Then set a project's `files_expire_at` to yesterday in the database, run `uv run celery -A src.celery_app call src.maintenance.tasks.expire_files`, and reload: the project shows as expired.

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: limit, expiry and quota messages in the UI"
```

---

## Done when

- Version 1 of the spec works end to end on a real recording.
- `uv run pytest` and the integration tests pass.
- `docs/rate-limiting.md` holds the comparison table and the decision.
- Concepts Nikhil can explain: the five rate limiting algorithms and their trade-offs, why the counter update must be atomic, fail open versus fail closed, why a cap on AI spend is a separate limit from a request limit, and what makes a scheduled job safe to run twice.
