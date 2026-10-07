# Milestone 4: Transcribe and Silence Cuts Implementation Plan

> **How this plan is executed:** learning mode, not an autonomous agent run. One task at a time, in small steps, with a stop for review after each. Each task has a **Who** line: `Claude` writes boilerplate and UI; `Nikhil` writes interview-critical code from the signatures and tests here, or reviews Claude's version with a planted bug, as he chooses per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A real uploaded video is checked, transcribed by ElevenLabs Scribe, and rendered with its silences cut out.

**Architecture:** The four fake stage bodies from Milestone 3 are replaced by real ones; the runner, tasks and endpoints do not change. Probe uses ffprobe and extracts the audio. Transcribe sends the audio to Scribe through a `Transcriber` interface. Plan turns gaps between words into drop ranges with pure functions. Render builds one ffmpeg filter graph that trims and joins the kept ranges.

**Tech Stack:** ffmpeg and ffprobe as subprocesses, httpx for the ElevenLabs API. Builds on Milestones 1 to 3.

**Spec:** `docs/superpowers/specs/2026-10-04-snipwise-design.md`

## Global Constraints

- All earlier constraints still apply.
- Video limits, checked from ffprobe output and never from the filename: at most 15 minutes (`max_duration_sec = 900`), short side at most 1080 pixels, must have an audio stream.
- ffmpeg and ffprobe are always run with an argument list (`subprocess` with `shell=False`). Paths and user text never go through a shell.
- Every stage works inside a temporary directory that is removed in a `finally`, including on failure and cancel.
- Silence rule: a gap between two words longer than 0.6 seconds is cut, keeping 0.15 seconds on each side. A kept piece shorter than 0.25 seconds is cut too.
- Times in segments are rounded to 3 decimals.
- Encoding: H.264 (`libx264 -preset veryfast -crf 20 -pix_fmt yuv420p`), AAC 160 kbit/s, MP4 with `-movflags +faststart`. Audio gets a 10 millisecond fade at each cut.
- Scribe request: `POST https://api.elevenlabs.io/v1/speech-to-text`, header `xi-api-key`, form fields `model_id=scribe_v2`, `timestamps_granularity=word`. `no_verbatim` is not sent, so filler words stay in.
- Keys: audio at `projects/{project_id}/audio.wav`, render at `renders/{render_id}.mp4`.
- User-facing failure messages are exact strings listed in the tasks. Internal details (stderr, API responses) are logged, never shown.

## Review Focus

1. A phone video recorded in portrait (rotation metadata): width and height reflect what the viewer sees, and the output is upright (Task 1 and Task 4).
2. A variable-frame-rate recording: audio and video stay in sync after cutting (Task 4).
3. Speech that starts at 0.0 or runs to the very end: no negative or zero-length ranges (Task 3).
4. A video with no speech at all: a clear failure message, not an empty render (Task 2).
5. A file with two audio streams, or 48 kHz stereo audio: the first audio stream is used (Task 1).

## File Structure

```
backend/src/
  media/
    ffprobe.py      probe() -> MediaInfo
    ffmpeg.py       run_ffmpeg(), extract_audio(), FfmpegError
  transcripts/
    types.py        Word, TranscriptResult
    transcriber.py  Transcriber protocol, FakeTranscriber, get_transcriber()
    scribe.py       ScribeTranscriber
    schemas.py  router.py
  edit_plans/
    timeline.py     Drop, TimeRange, silence_drops, build_segments, keep_ranges, kept_duration
    schemas.py  router.py
  renders/
    filter_graph.py RenderOptions, build_filter_graph
    render.py       render_video
  pipeline/
    workdir.py      stage_workdir()
    stages/probe.py  stages/transcribe.py  stages/plan.py  stages/render.py
    tasks.py        stage_work() picks fake or real by settings.pipeline_mode
backend/tests/
  media_fixtures.py   make_video()
  fixtures/scribe_response.json
```

---

### Task 1: ffprobe, the ffmpeg runner and the probe stage

**Who:** Nikhil

**Files:**
- Create: `backend/src/media/{__init__,ffprobe,ffmpeg}.py`, `backend/src/pipeline/workdir.py`, `backend/src/pipeline/stages/{__init__,probe}.py`
- Create: `backend/tests/media_fixtures.py`
- Modify: `backend/src/config.py`, `backend/src/users/service.py`, `backend/tests/conftest.py`
- Test: `backend/tests/media/test_ffprobe.py`, `backend/tests/media/test_ffmpeg.py`, `backend/tests/pipeline/test_probe_stage.py`

**Interfaces:**
- Consumes: `StageContext`, `PermanentStageError`, `get_storage`.
- Produces:
  - Settings: `ffmpeg_bin: str = "ffmpeg"`, `ffprobe_bin: str = "ffprobe"`, `max_duration_sec: int = 900`, `max_short_side: int = 1080`, `pipeline_mode: Literal["fake", "real"] = "real"`.
  - `media.ffprobe`:
    ```python
    @dataclass(frozen=True)
    class MediaInfo:
        duration_sec: float; width: int; height: int; fps: float; has_audio: bool; video_codec: str
    class NotAVideoError(Exception): ...
    def probe(path: Path) -> MediaInfo
    ```
    Runs `ffprobe -v error -print_format json -show_format -show_streams <path>`. Uses the first video stream and `format.duration`. `fps` comes from `avg_frame_rate`. If the stream's display rotation is 90 or 270 (side data `rotation`, or the `rotate` tag), `width` and `height` are swapped. No video stream, non-zero exit or unparsable output → `NotAVideoError`.
  - `media.ffmpeg`:
    ```python
    class FfmpegError(Exception): ...        # str() is the last 2000 characters of stderr
    def run_ffmpeg(args: list[str], *, duration_sec: float | None = None, on_progress: Callable[[int], None] | None = None) -> None
    def extract_audio(src: Path, dest: Path) -> None
    def extract_thumbnail(src: Path, dest: Path, at_sec: float) -> None      # one JPEG frame, 480 pixels wide
    ```
    `run_ffmpeg` runs `[ffmpeg_bin, "-hide_banner", "-nostdin", "-y", *args, "-progress", "pipe:1", "-nostats"]`, reads `out_time_us=` lines and calls `on_progress(percent)` with `out_time / duration_sec`. If `on_progress` raises, it terminates the process (kill after 5 seconds) and re-raises. Non-zero exit → `FfmpegError`. `extract_audio` uses `-i src -map 0:a:0 -vn -ac 1 -ar 16000 -c:a pcm_s16le dest`.
  - `pipeline.workdir.stage_workdir() -> ContextManager[Path]`: a `tempfile.mkdtemp(prefix="stage-")` directory, removed with `shutil.rmtree(..., ignore_errors=True)` in `finally`.
  - `users.service.minutes_used_this_month_sync(session: Session, user_id: UUID) -> float`: same query as the async version, sharing one statement-building helper.
  - `pipeline.stages.probe.probe_stage(ctx: StageContext) -> None`: downloads the source, probes it, validates, saves `duration_sec, width, height, fps` on the project, extracts audio and uploads it to `projects/{id}/audio.wav` (`audio/wav`), and uploads a thumbnail taken at `min(1.0, duration_sec / 2)` to `projects/{id}/thumb.jpg` (`image/jpeg`). Reports 10, 40, 80, 100.
  - `ProjectOut` gains `thumbnail_url: str | None`: a 5-minute presigned link to `thumb.jpg` when `duration_sec` is set and the status is not `expired`, else `null`. Failure messages (`PermanentStageError`):
    - `NotAVideoError` → `"This file is not a video we can read."`
    - no audio → `"This video has no audio track."`
    - too long → `"Videos can be at most 15 minutes long."`
    - `min(width, height) > max_short_side` → `"Videos can be at most 1080p."`
    - `duration_sec / 60 > free_minutes_per_month - minutes_used_this_month_sync(...)` → `"This video is longer than your remaining minutes this month."`
  - `tests/media_fixtures.py`:
    ```python
    def make_video(path: Path, *, seconds: float = 7.0, size: str = "640x360", fps: int = 30, audio: bool = True,
                   silent: tuple[float, float] | None = (2.0, 5.0), rotation: int | None = None, audio_streams: int = 1) -> Path
    ```
    Built with ffmpeg `lavfi` sources (`testsrc` and `sine=frequency=440`), silence made with `volume=enable='between(t,2,5)':volume=0`. Rotation is applied by remuxing with the input option `-display_rotation`. Session-scoped fixtures: `sample_video` (defaults), `no_audio_video`, `portrait_video` (`rotation=90`), `two_audio_video`, `not_a_video` (a text file named `.mp4`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/media/test_ffprobe.py
def test_probe_reads_a_normal_video(sample_video):
    info = probe(sample_video)
    assert (info.width, info.height, info.has_audio, info.video_codec) == (640, 360, True, "h264")
    assert info.duration_sec == pytest.approx(7.0, abs=0.1) and info.fps == pytest.approx(30, abs=0.1)

def test_probe_swaps_dimensions_for_rotated_video(portrait_video):
    info = probe(portrait_video)
    assert (info.width, info.height) == (360, 640)

def test_probe_reports_missing_audio(no_audio_video):
    assert probe(no_audio_video).has_audio is False

def test_probe_rejects_non_video(not_a_video):
    with pytest.raises(NotAVideoError):
        probe(not_a_video)
```

```python
# tests/media/test_ffmpeg.py
def test_extract_audio_is_16k_mono_from_first_stream(two_audio_video, tmp_path):
    out = tmp_path / "a.wav"
    extract_audio(two_audio_video, out)
    with wave.open(str(out)) as w:
        assert (w.getframerate(), w.getnchannels()) == (16000, 1)
        assert w.getnframes() / 16000 == pytest.approx(7.0, abs=0.1)

def test_run_ffmpeg_reports_progress_and_raises_on_failure(sample_video, tmp_path):
    seen = []
    run_ffmpeg(["-i", str(sample_video), "-c", "copy", str(tmp_path / "o.mp4")], duration_sec=7.0, on_progress=seen.append)
    assert seen and seen[-1] >= 90
    with pytest.raises(FfmpegError):
        run_ffmpeg(["-i", str(tmp_path / "missing.mp4"), str(tmp_path / "x.mp4")])

def test_run_ffmpeg_stops_the_process_when_progress_callback_raises(sample_video, tmp_path):
    def stop(_): raise StageCancelled()
    with pytest.raises(StageCancelled):
        run_ffmpeg(["-i", str(sample_video), "-vf", "scale=1920:1080", str(tmp_path / "o.mp4")], duration_sec=7.0, on_progress=stop)
    assert not any("ffmpeg" in p.name() for p in psutil.Process().children(recursive=True))

def test_workdir_is_removed_even_on_error():
    with pytest.raises(RuntimeError):
        with stage_workdir() as d:
            (d / "f").write_text("x"); raise RuntimeError
    assert not d.exists()
```

```python
# tests/pipeline/test_probe_stage.py      (`staged(video)`: puts the file's bytes at the project's source key in MemoryStorage, returns a processing project)
def test_probe_saves_metadata_and_audio(sync_db, storage, staged, sample_video):
    p = staged(sample_video)
    run_stage(p.id, Stage.probe, probe_stage)
    sync_db.expire_all(); p = sync_db.get(Project, p.id)
    assert (p.width, p.height) == (640, 360) and p.duration_sec == pytest.approx(7.0, abs=0.1)
    assert storage.object_size(f"projects/{p.id}/audio.wav") > 0
    assert storage.object_size(f"projects/{p.id}/thumb.jpg") > 0

@pytest.mark.parametrize("fixture,override,message", [
    ("not_a_video", {}, "This file is not a video we can read."),
    ("no_audio_video", {}, "This video has no audio track."),
    ("sample_video", {"max_duration_sec": 5}, "Videos can be at most 15 minutes long."),
    ("sample_video", {"max_short_side": 240}, "Videos can be at most 1080p."),
    ("sample_video", {"free_minutes_per_month": 0}, "This video is longer than your remaining minutes this month."),
])
def test_probe_rejections(request, sync_db, staged, settings_override, fixture, override, message):
    settings_override(**override)
    p = staged(request.getfixturevalue(fixture))
    with pytest.raises(PermanentStageError, match=re.escape(message)):
        run_stage(p.id, Stage.probe, probe_stage)
    sync_db.expire_all()
    assert sync_db.get(Project, p.id).status == ProjectStatus.failed
```

- [ ] **Step 2: Run to see them fail**

Run: `uv add --dev psutil && uv run pytest tests/media tests/pipeline/test_probe_stage.py -v`
Expected: FAIL, modules not found.

- [ ] **Step 3: Write `media_fixtures.py`**, then `ffprobe.py`, `ffmpeg.py`, `workdir.py`.

- [ ] **Step 4: Write `minutes_used_this_month_sync` and `stages/probe.py`.**

- [ ] **Step 5: Run the tests to see them pass**

Run: `uv run pytest tests/media tests/pipeline/test_probe_stage.py -v`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: ffprobe, ffmpeg runner and the probe stage"
```

---

### Task 2: Transcriber interface, Scribe client and the transcribe stage

**Who:** Nikhil (calling a paid API safely: timeouts, error classes, no secrets in logs)

**Files:**
- Create: `backend/src/transcripts/{types,transcriber,scribe}.py`, `backend/src/pipeline/stages/transcribe.py`
- Modify: `backend/src/pipeline/errors.py` (add `TransientApiError`)
- Create: `backend/tests/fixtures/scribe_response.json`
- Modify: `backend/src/config.py`, `backend/.env.example`, `backend/.env`
- Test: `backend/tests/transcripts/test_scribe.py`, `backend/tests/pipeline/test_transcribe_stage.py`

**Interfaces:**
- Consumes: `StageContext`, `PermanentStageError`, `Transcript` model, `stage_workdir`.
- Produces:
  - Settings: `transcriber: Literal["fake", "scribe"] = "scribe"`, `elevenlabs_api_key: SecretStr | None = None`, `scribe_model: str = "scribe_v2"`. Tests set `TRANSCRIBER=fake`.
  - `transcripts.types`:
    ```python
    @dataclass(frozen=True)
    class Word:
        text: str; start: float; end: float; type: Literal["word", "audio_event"] = "word"; confidence: float | None = None
        def to_json(self) -> dict: ...
        @classmethod
        def from_json(cls, d: dict) -> "Word": ...

    @dataclass(frozen=True)
    class TranscriptResult:
        language: str; model: str; words: list[Word]
    ```
  - `transcripts.transcriber`: `class Transcriber(Protocol): def transcribe(self, audio_path: Path) -> TranscriptResult`; `class FakeTranscriber` (constructed with `words: list[Word]`, class attribute `default_words` that tests can set); `get_transcriber() -> Transcriber`.
  - `transcripts.scribe`:
    ```python
    class ScribeTranscriber:
        def __init__(self, api_key: str, model: str = "scribe_v2", client: httpx.Client | None = None): ...
        def transcribe(self, audio_path: Path) -> TranscriptResult
    ```
    `TransientApiError` is a new plain exception added to `pipeline/errors.py` in this task (Celery retries it; Milestone 5 reuses it for Gemini). Timeout `httpx.Timeout(connect=10, read=300, write=300, pool=10)`. Status 429 or 5xx, or any `httpx.TransportError` → `TransientApiError`. Any other non-2xx → `PermanentStageError("We could not transcribe this video.")`. From the response: skip entries with `type == "spacing"`; keep `word` and `audio_event`; `confidence = round(math.exp(logprob), 3)` when `logprob` is present; `language` from `language_code`; words sorted by `start`. The API key must not appear in any exception message or log line.
  - `pipeline.stages.transcribe.transcribe_stage(ctx)`: downloads `audio.wav`, calls `get_transcriber().transcribe(...)`, raises `PermanentStageError("No speech found in this video.")` when no entry has `type == "word"`, clamps each `end` to `project.duration_sec`, and replaces the project's `Transcript` row (`audio_seconds = project.duration_sec`). Reports 10, 90, 100.

- [ ] **Step 1: Confirm the response shape against the live docs**

Open `https://elevenlabs.io/docs/api-reference/speech-to-text/convert`. Confirm the field names used above (`words[].text/start/end/type/logprob`, `language_code`) and the `type` values. Save a response sample in `tests/fixtures/scribe_response.json` with these six entries, in order: word `"So"` 0.10 to 0.40; spacing; word `"um"` 0.90 to 1.20 (logprob −0.105); spacing; audio_event `"(laughs)"` 1.50 to 2.00; word `"hello"` 2.10 to 2.60. `language_code` is `"en"`.
If the docs differ, change the fixture and the parsing rule to match the docs, and note the difference in the spec.

- [ ] **Step 2: Write the failing tests**

```python
# tests/transcripts/test_scribe.py
def make(handler):
    return ScribeTranscriber("secret-key-123", client=httpx.Client(transport=httpx.MockTransport(handler)))

def test_parses_words_and_skips_spacing(sample_wav, scribe_json):
    def handler(req):
        assert req.url == "https://api.elevenlabs.io/v1/speech-to-text" and req.headers["xi-api-key"] == "secret-key-123"
        body = req.read()
        assert b"scribe_v2" in body and b"timestamps_granularity" in body and b"no_verbatim" not in body
        return httpx.Response(200, json=scribe_json)
    result = make(handler).transcribe(sample_wav)
    assert [(w.text, w.type) for w in result.words] == [("So", "word"), ("um", "word"), ("(laughs)", "audio_event"), ("hello", "word")]
    assert result.words[1].confidence == 0.9 and result.language == "en" and result.model == "scribe_v2"

@pytest.mark.parametrize("status", [429, 500, 503])
def test_temporary_statuses_are_retryable(sample_wav, status):
    with pytest.raises(TransientApiError):
        make(lambda req: httpx.Response(status, json={"detail": "x"})).transcribe(sample_wav)

def test_network_error_is_retryable(sample_wav):
    def handler(req): raise httpx.ConnectTimeout("slow")
    with pytest.raises(TransientApiError):
        make(handler).transcribe(sample_wav)

def test_client_error_is_permanent_and_hides_the_key(sample_wav):
    with pytest.raises(PermanentStageError) as e:
        make(lambda req: httpx.Response(401, json={"detail": "bad key secret-key-123"})).transcribe(sample_wav)
    assert str(e.value) == "We could not transcribe this video." and "secret-key-123" not in repr(e.value)
```

```python
# tests/pipeline/test_transcribe_stage.py     (`probed`: a processing project whose probe stage already ran on sample_video)
WORDS = [Word("one", 0.1, 0.9), Word("two", 1.0, 1.9), Word("three", 5.1, 5.9), Word("four", 6.0, 7.4)]

def test_transcribe_saves_words_and_clamps_to_duration(sync_db, probed):
    FakeTranscriber.default_words = WORDS
    run_stage(probed.id, Stage.transcribe, transcribe_stage)
    t = sync_db.scalar(select(Transcript).where(Transcript.project_id == probed.id))
    assert len(t.words) == 4 and t.words[-1]["end"] == pytest.approx(probed.duration_sec, abs=0.01)
    assert t.audio_seconds == pytest.approx(7.0, abs=0.1)

def test_running_twice_keeps_one_transcript(sync_db, probed):
    FakeTranscriber.default_words = WORDS
    transcribe_stage_direct(probed.id); transcribe_stage_direct(probed.id)        # helper: call the stage body without the skip
    assert sync_db.scalar(select(func.count()).select_from(Transcript).where(Transcript.project_id == probed.id)) == 1

def test_no_speech_fails_with_clear_message(sync_db, probed):
    FakeTranscriber.default_words = [Word("(music)", 0.0, 7.0, type="audio_event")]
    with pytest.raises(PermanentStageError, match="No speech found in this video."):
        run_stage(probed.id, Stage.transcribe, transcribe_stage)
```

- [ ] **Step 3: Run to see them fail**

Run: `uv run pytest tests/transcripts tests/pipeline/test_transcribe_stage.py -v`
Expected: FAIL, modules not found.

- [ ] **Step 4: Write `types.py`, `transcriber.py`, `scribe.py`, `stages/transcribe.py`.**

- [ ] **Step 5: Run the tests to see them pass**

Run: `uv run pytest tests/transcripts tests/pipeline/test_transcribe_stage.py -v`
Expected: all passed.

- [ ] **Step 6: One live call**

Put the real key in `.env` as `ELEVENLABS_API_KEY`. Record a 20-second clip saying "So, um, hello. Hello and welcome. Uh, today..." with a 2-second pause. Run a small script that extracts its audio and prints `ScribeTranscriber(...).transcribe(path).words`.
Expected: "um" and "uh" are present as words, each word has a start and end, and the 2-second pause shows as a gap between two word times. Write the gap you measured next to the real pause length in `docs/benchmarks.md`. If gaps are off by more than 0.3 seconds, raise it before Task 3 (the spec's fallback is Silero VAD).

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: transcriber interface, Scribe client, transcribe stage"
```

---

### Task 3: Timeline maths

**Who:** Nikhil (pure functions, the heart of the cutting logic)

**Files:**
- Create: `backend/src/edit_plans/timeline.py`
- Modify: `backend/src/config.py`
- Test: `backend/tests/edit_plans/test_timeline.py`

**Interfaces:**
- Consumes: `Word`.
- Produces:
  - Settings: `silence_min_gap_sec: float = 0.6`, `silence_pad_sec: float = 0.15`, `min_keep_sec: float = 0.25`.
  - ```python
    @dataclass(frozen=True)
    class TimeRange:
        start: float; end: float

    @dataclass(frozen=True)
    class Drop:
        start: float; end: float; reason: str                # "silence" | "filler" | "retake"

    REASON_PRIORITY = {"retake": 3, "filler": 2, "silence": 1}

    def silence_drops(words: list[Word], duration: float, *, min_gap: float = 0.6, pad: float = 0.15) -> list[Drop]
    def build_segments(duration: float, drops: list[Drop], *, min_keep: float = 0.25) -> list[dict]
    def keep_ranges(segments: list[dict]) -> list[TimeRange]
    def kept_duration(segments: list[dict]) -> float
    ```
  - `silence_drops`: looks at the gap before the first word (from 0), between each pair of neighbours, and after the last word (to `duration`). A gap longer than `min_gap` gives a drop: `[0, first.start - pad]` at the head, `[a.end + pad, b.start - pad]` in the middle, `[last.end + pad, duration]` at the tail. All entries count as speech, including `audio_event`. Drop times are rounded to 3 decimals.
  - `build_segments`: clamps drops to `[0, duration]`, discards empty ones, sorts, merges overlapping or touching drops (the merged reason is the one with the highest `REASON_PRIORITY`), turns any kept piece shorter than `min_keep` into part of the neighbouring drop, and returns contiguous segments from `0.0` to `duration` in the segment JSON shape, rounded to 3 decimals. No drops → one keep segment.

- [ ] **Step 1: Write the failing tests**

```python
# tests/edit_plans/test_timeline.py
W = lambda s, e: Word("w", s, e)

def test_silence_drops_head_middle_tail():
    words = [W(1.0, 1.5), W(1.6, 2.0), W(5.0, 5.5)]
    assert silence_drops(words, 7.0) == [Drop(0.0, 0.85, "silence"), Drop(2.15, 4.85, "silence"), Drop(5.65, 7.0, "silence")]

def test_gap_shorter_than_min_gap_is_kept():
    assert silence_drops([W(0.0, 1.0), W(1.5, 2.0)], 2.0) == []

def test_speech_touching_both_ends_gives_no_drops():
    assert silence_drops([W(0.0, 3.0), W(3.1, 7.0)], 7.0) == []

def test_build_segments_is_contiguous_and_covers_everything():
    segs = build_segments(7.0, [Drop(0.0, 0.85, "silence"), Drop(2.15, 4.85, "silence"), Drop(5.65, 7.0, "silence")])
    assert [(s["start"], s["end"], s["action"]) for s in segs] == [
        (0.0, 0.85, "drop"), (0.85, 2.15, "keep"), (2.15, 4.85, "drop"), (4.85, 5.65, "keep"), (5.65, 7.0, "drop")]
    assert all(a["end"] == b["start"] for a, b in zip(segs, segs[1:]))
    assert kept_duration(segs) == pytest.approx(2.1)
    assert keep_ranges(segs) == [TimeRange(0.85, 2.15), TimeRange(4.85, 5.65)]

def test_no_drops_is_one_keep_segment():
    assert build_segments(7.0, []) == [{"start": 0.0, "end": 7.0, "action": "keep", "reason": None}]

def test_overlapping_drops_merge_and_take_the_stronger_reason():
    segs = build_segments(10.0, [Drop(2.0, 4.0, "silence"), Drop(3.5, 5.0, "retake"), Drop(5.0, 6.0, "filler")])
    assert [(s["start"], s["end"], s["action"], s["reason"]) for s in segs] == [
        (0.0, 2.0, "keep", None), (2.0, 6.0, "drop", "retake"), (6.0, 10.0, "keep", None)]

def test_tiny_keep_between_two_drops_is_dropped():
    segs = build_segments(10.0, [Drop(2.0, 4.0, "silence"), Drop(4.1, 6.0, "filler")])
    assert [(s["start"], s["end"], s["action"], s["reason"]) for s in segs] == [
        (0.0, 2.0, "keep", None), (2.0, 6.0, "drop", "filler"), (6.0, 10.0, "keep", None)]

def test_out_of_range_and_empty_drops_are_ignored():
    segs = build_segments(5.0, [Drop(-1.0, 0.0, "silence"), Drop(3.0, 3.0, "silence"), Drop(4.0, 9.0, "silence")])
    assert [(s["start"], s["end"], s["action"]) for s in segs] == [(0.0, 4.0, "keep"), (4.0, 5.0, "drop")]

def test_times_are_rounded_to_three_decimals():
    segs = build_segments(1.0, [Drop(0.1234567, 0.7654321, "silence")])
    assert segs[1]["start"] == 0.123 and segs[1]["end"] == 0.765
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/edit_plans/test_timeline.py -v`
Expected: FAIL, module not found.

- [ ] **Step 3: Write `timeline.py`.**

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/edit_plans/test_timeline.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: silence detection and segment building"
```

---

### Task 4: The plan stage, the filter graph and the render stage

**Who:** Nikhil

**Files:**
- Create: `backend/src/renders/{filter_graph,render}.py`, `backend/src/pipeline/stages/{plan,render}.py`
- Modify: `backend/src/pipeline/tasks.py`, `backend/tests/conftest.py`
- Test: `backend/tests/renders/test_filter_graph.py`, `backend/tests/pipeline/test_real_pipeline.py`

**Interfaces:**
- Consumes: `silence_drops`, `build_segments`, `keep_ranges`, `kept_duration`, `run_ffmpeg`, `probe`, `stage_workdir`, `Transcript`, `EditPlan`, `Render`.
- Produces:
  - `renders.filter_graph`:
    ```python
    @dataclass(frozen=True)
    class RenderOptions:
        fps: int; width: int; height: int
        zoom: bool = False; color: bool = False; captions_path: Path | None = None     # used from Milestone 6
    def build_filter_graph(keeps: list[TimeRange], opts: RenderOptions) -> str
    ```
    The graph always ends with the labels `[vout]` and `[aout]`. Video starts with `fps=<opts.fps>` (this also fixes variable-frame-rate input). For N keeps: `split=N` / `asplit=N`, then per keep `trim=start=S:end=E,setpts=PTS-STARTPTS` and `atrim=start=S:end=E,asetpts=PTS-STARTPTS,afade=t=in:d=0.01,afade=t=out:st=<E-S-0.01>:d=0.01`, then `concat=n=N:v=1:a=1[vout][aout]`. For one keep there is no `split` and no `concat`. Numbers are formatted with 3 decimals. Empty `keeps` → `ValueError`.
  - `renders.render.render_video(src: Path, dest: Path, keeps: list[TimeRange], opts: RenderOptions, *, on_progress: Callable[[int], None] | None = None) -> None`: one `run_ffmpeg` call with `-i src -filter_complex <graph> -map [vout] -map [aout]` and the encoding flags from Global Constraints; `duration_sec` is the summed keep length.
  - `pipeline.stages.plan.plan_stage(ctx)`: returns at once if the project already has an edit plan. Otherwise builds `drops = silence_drops(words, duration, ...)` when `options.remove_silences` else `[]`, then `segments = build_segments(...)`. If `kept_duration(segments) < 0.5` → `PermanentStageError("Nothing would be left after editing this video.")`. Inserts `EditPlan(version=1, created_by="ai", segments=segments)`.
  - `pipeline.stages.render.render_stage(ctx)`: loads the render and its plan, marks the render `running`, downloads the source, calls `render_video` with `RenderOptions(fps=min(round(project.fps or 30), 60), width=project.width, height=project.height)` and `on_progress=ctx.report`, probes the output, uploads it to `renders/{render_id}.mp4` (`video/mp4`), and saves `output_key`, `duration_sec`, `size_bytes`.
  - `pipeline.tasks.stage_work(stage: Stage) -> Callable[[StageContext], None]`: returns the fake body when `settings.pipeline_mode == "fake"`, else the real one. It replaces the `STAGE_WORK` dict. `conftest.py` sets `PIPELINE_MODE=fake` by default so the Milestone 3 tests keep passing.

- [ ] **Step 1: Write the failing tests**

```python
# tests/renders/test_filter_graph.py
OPTS = RenderOptions(fps=30, width=640, height=360)

def test_two_keeps():
    g = build_filter_graph([TimeRange(0.85, 2.15), TimeRange(4.85, 5.65)], OPTS)
    assert g.startswith("[0:v]fps=30,split=2")
    assert "trim=start=0.850:end=2.150,setpts=PTS-STARTPTS" in g
    assert "atrim=start=4.850:end=5.650,asetpts=PTS-STARTPTS,afade=t=in:d=0.01,afade=t=out:st=0.790:d=0.01" in g
    assert g.endswith("concat=n=2:v=1:a=1[vout][aout]")

def test_single_keep_has_no_split_or_concat():
    g = build_filter_graph([TimeRange(0.0, 7.0)], OPTS)
    assert "split" not in g and "concat" not in g and "[vout]" in g and "[aout]" in g

def test_empty_keeps_is_an_error():
    with pytest.raises(ValueError):
        build_filter_graph([], OPTS)
```

```python
# tests/pipeline/test_real_pipeline.py      (real ffmpeg, MemoryStorage, FakeTranscriber; settings_override(pipeline_mode="real"))
WORDS = [Word("one", 0.1, 0.9), Word("two", 1.0, 1.9), Word("three", 5.1, 5.9), Word("four", 6.0, 6.9)]

async def test_silence_is_cut_end_to_end(client, user_headers, storage, upload_file, sample_video, tmp_path):
    FakeTranscriber.default_words = WORDS
    project = await upload_file(sample_video)                 # start, put parts, complete (runs probe→transcribe→plan eagerly)
    pid = project["id"]
    assert (await client.get(f"/api/projects/{pid}", headers=user_headers)).json()["status"] == "ready_for_review"
    render = (await client.post(f"/api/projects/{pid}/renders", headers=user_headers)).json()
    out = tmp_path / "out.mp4"; storage.download_file(f"renders/{render['id']}.mp4", out)
    info = probe(out)
    assert info.duration_sec == pytest.approx(4.1, abs=0.15)          # 7.0 minus the 2.05–4.95 silence
    assert info.has_audio and (info.width, info.height) == (640, 360)

async def test_portrait_video_stays_upright(client, user_headers, storage, upload_file, portrait_video, tmp_path):
    FakeTranscriber.default_words = WORDS
    pid = (await upload_file(portrait_video))["id"]
    render = (await client.post(f"/api/projects/{pid}/renders", headers=user_headers)).json()
    out = tmp_path / "out.mp4"; storage.download_file(f"renders/{render['id']}.mp4", out)
    assert (probe(out).width, probe(out).height) == (360, 640)

async def test_silences_off_keeps_the_whole_video(client, user_headers, storage, upload_file, sample_video, sync_db):
    FakeTranscriber.default_words = WORDS
    pid = (await upload_file(sample_video, options={"removeSilences": False}))["id"]
    plan = sync_db.scalar(select(EditPlan).where(EditPlan.project_id == UUID(pid)))
    assert [s["action"] for s in plan.segments] == ["keep"]

def test_plan_stage_twice_creates_one_plan(sync_db, transcribed):       # `transcribed`: project with a Transcript
    plan_stage_direct(transcribed.id); plan_stage_direct(transcribed.id)
    assert sync_db.scalar(select(func.count()).select_from(EditPlan).where(EditPlan.project_id == transcribed.id)) == 1

def test_no_temp_files_are_left_behind(...):
    ...  # count entries in tempfile.gettempdir() starting with "stage-" before and after a full run: equal
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/renders tests/pipeline/test_real_pipeline.py -v`
Expected: FAIL, modules not found.

- [ ] **Step 3: Write `filter_graph.py` and `render.py`.**

- [ ] **Step 4: Write `stages/plan.py` and `stages/render.py`, and switch `tasks.py` to `stage_work()`.**

- [ ] **Step 5: Run every test**

Run: `uv run pytest -v`
Expected: all passed, including the Milestone 3 tests (they run in fake mode).

- [ ] **Step 6: Real-video check and timings**

With `TRANSCRIBER=scribe` and `PIPELINE_MODE=real`, upload two real recordings through the UI: a 10-minute landscape screen or camera recording, and a 1-minute portrait phone clip (phones record variable frame rate). For each, watch the result and check: silences are gone, no cut clips a word, lips and audio stay in sync at the end of the video, the portrait clip is upright. Record in `docs/benchmarks.md`: video length, number of cuts, transcribe seconds, render seconds.
Expected: sync holds to the end. If the 10-minute render takes longer than the video itself, note it for Milestone 7.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: real plan and render stages with silence cuts"
```

---

### Task 5: Read endpoints and the result view

**Who:** Claude

**Files:**
- Create: `backend/src/transcripts/{schemas,router}.py`, `backend/src/edit_plans/{schemas,router}.py`
- Modify: `backend/src/main.py`, `frontend/src/app/(app)/projects/[id]/page.tsx`
- Test: `backend/tests/edit_plans/test_read_api.py`

**Interfaces:**
- Produces:
  - `GET /api/projects/{id}/transcript` → `{language, words: [{text, start, end, type}]}`; 404 `not_found` when there is none.
  - `GET /api/projects/{id}/edit-plans/latest` → `EditPlanOut(version, created_by, segments, fallback_used, fallback_reason, original_duration_sec, kept_duration_sec, created_at)`; 404 when there is none.
  - Frontend: dashboard cards show the project's `thumbnailUrl` (a neutral placeholder when it is `null` or fails to load); the `ready_for_review` view shows "N cuts, M:SS removed" above the Render button; the `done` view shows "12:04 → 7:18, 4:46 removed" from the plan's two durations.

- [ ] **Step 1: Write the failing tests**

```python
# tests/edit_plans/test_read_api.py
async def test_transcript_and_latest_plan(client, user_headers, uploaded_project):       # fake mode
    pid = uploaded_project["id"]
    t = await client.get(f"/api/projects/{pid}/transcript", headers=user_headers)
    assert t.status_code == 200 and t.json()["language"] == "en"
    p = (await client.get(f"/api/projects/{pid}/edit-plans/latest", headers=user_headers)).json()
    assert p["version"] == 1 and p["createdBy"] == "ai" and p["originalDurationSec"] == 60.0 and p["keptDurationSec"] == 60.0

async def test_missing_and_foreign_are_404(client, user_headers, other_headers, new_project, uploaded_project):
    assert (await client.get(f"/api/projects/{new_project['id']}/transcript", headers=user_headers)).status_code == 404
    assert (await client.get(f"/api/projects/{new_project['id']}/edit-plans/latest", headers=user_headers)).status_code == 404
    assert (await client.get(f"/api/projects/{uploaded_project['id']}/transcript", headers=other_headers)).status_code == 404
```

- [ ] **Step 2: Run to see them fail, write the two routers and schemas, run to see them pass**

Run: `uv run pytest tests/edit_plans/test_read_api.py -v`
Expected: FAIL first, then all passed.

- [ ] **Step 3: Update the two frontend views, then `npm run lint && npm run build`**

Expected: both succeed, and the browser shows the removed-time summary on a real project.

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: transcript and edit plan read endpoints, removed-time summary"
```

---

## Done when

- A real talking-head video uploaded through the UI comes back with its silences cut, in sync, and upright.
- `uv run pytest` passes with ffmpeg installed.
- `docs/benchmarks.md` holds the first timing numbers and the measured word-gap accuracy.
- Concepts Nikhil can explain: why cuts need a re-encode, what the filter graph does step by step, why ffmpeg runs as a separate process and how cancel stops it, how to call a paid API safely (timeouts, which errors retry, no secrets in logs), and why the timeline logic is pure functions.
