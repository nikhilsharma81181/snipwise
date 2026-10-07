# Milestone 1: Foundation Implementation Plan

> **How this plan is executed:** learning mode, not an autonomous agent run. One task at a time, in small steps, with a stop for review after each. Each task has a **Who** line: `Claude` writes boilerplate and UI; `Nikhil` writes interview-critical code from the signatures and tests here, or reviews Claude's version with a planted bug, as he chooses per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A running FastAPI app where a user can sign up, log in, and create, list, rename and delete their own projects, with Postgres, Redis and MinIO running locally and a thin Next.js UI for login and the dashboard.

**Architecture:** One FastAPI app in `backend/` with a folder per domain (`auth`, `users`, `projects`), async SQLAlchemy on Postgres, and Alembic migrations. Auth uses a 15-minute access JWT held in browser memory and a rotating refresh token in an httpOnly cookie. Next.js in `frontend/` is UI only and calls the API.

**Tech Stack:** Python 3.14, uv, FastAPI, SQLAlchemy 2 (asyncpg), Alembic, pydantic-settings, PyJWT, pwdlib (Argon2id), pytest, pytest-asyncio, httpx, ruff. Postgres 17, Redis 7, MinIO in Docker Compose. Next.js (App Router, TypeScript, Tailwind).

**Spec:** `docs/superpowers/specs/2026-10-04-snipwise-design.md`

## Global Constraints

- All API routes are mounted under `/api` (the spec's `/auth/login` is served at `/api/auth/login`).
- Every error response is `{"code": "<snake_case>", "message": "<text>"}`. Validation errors add `"issues": [{"field", "message"}]`. Statuses used: 401, 403, 404, 409, 413, 422, 429.
- JSON uses camelCase (`CamelModel`), Python uses snake_case.
- All ids are UUID v7 (`uuid.uuid7`). All tables have `created_at timestamptz DEFAULT now()`. Table and column names are snake_case.
- Every project query is scoped to the owner. Another user's project returns 404, never 403.
- Free quota: 60 minutes of video per calendar month (UTC), calculated, never stored.
- Access token lifetime 15 minutes. Refresh token lifetime 7 days, stored only as a SHA-256 hash, rotated on every use.
- CORS allows only `settings.frontend_origin` (`http://localhost:3000` locally), with credentials.
- Request bodies are validated with Pydantic. Use `parsed` data only, never raw input.
- Commit after every task. Never commit `.env`.

## Review Focus

Inputs the spec implies but does not spell out. Each has a test in the task named.

1. The same email typed as `A@Test.com ` and `a@test.com` is one account, not two (Task 3).
2. Two refresh requests sent at the same moment with the same token: exactly one succeeds (Task 3).
3. A `cursor` that is not a UUID returns 422, and a valid UUID that matches nothing returns an empty page, never a 500 (Task 4).
4. A password longer than 72 bytes or containing non-ASCII characters can sign up and log in (Task 3).
5. A deleted project's id returns 404 on GET, PATCH and DELETE, and it is gone from the list (Task 4).

## File Structure

```
snipwise/
  docker-compose.yml            Postgres, Redis, MinIO, bucket init
  docker/postgres-init.sql      creates the test database
  .gitignore
  backend/
    pyproject.toml  .env.example  alembic.ini
    alembic/env.py  alembic/versions/
    src/
      main.py          app, CORS, routers, lifespan
      config.py        Settings
      database.py      async engine, get_db, DbSession
      models.py        Base with constraint naming convention
      schemas.py       CamelModel
      exceptions.py    AppError classes + handlers ({code, message})
      auth/    config.py utils.py models.py schemas.py exceptions.py service.py dependencies.py router.py
      users/   models.py schemas.py service.py router.py
      projects/ models.py schemas.py status.py service.py dependencies.py router.py exceptions.py
    tests/
      conftest.py  test_health.py  auth/  projects/
  frontend/
    src/lib/api.ts  src/lib/auth-context.tsx
    src/app/(auth)/login/page.tsx  src/app/(auth)/signup/page.tsx
    src/app/(app)/layout.tsx  src/app/(app)/dashboard/page.tsx
```

Reference code to copy from: `/Users/nikhilsharma/Important/backend-prototype/almarbatt_lite_py/src/`. Its `config.py`, `database.py`, `models.py`, `schemas.py`, `exceptions.py`, `auth/utils.py`, `auth/config.py` and `auth/exceptions.py` are complete. Its `auth/service.py`, `auth/router.py` and `auth/dependencies.py` are empty stubs, so those are written new in Task 3.

---

### Task 1: Repository, local services and app skeleton

**Who:** Claude

**Files:**
- Create: `.gitignore`, `docker-compose.yml`, `docker/postgres-init.sql`
- Create: `backend/pyproject.toml`, `backend/.env.example`, `backend/.env`
- Create: `backend/src/{main,config,database,models,schemas,exceptions}.py`, `backend/src/__init__.py`
- Create: `backend/alembic.ini`, `backend/alembic/env.py`
- Test: `backend/tests/conftest.py`, `backend/tests/test_health.py`

**Interfaces:**
- Produces:
  - `src.config.settings` with fields: `environment: Literal["development","production"]`, `database_url: PostgresDsn`, `redis_url: RedisDsn`, `frontend_origin: str = "http://localhost:3000"`, `free_minutes_per_month: int = 60`.
  - `src.database`: `engine`, `SessionLocal`, `get_db`, `DbSession`.
  - `src.models.Base` (DeclarativeBase with a `MetaData(naming_convention=...)` for `ix`, `uq`, `ck`, `fk`, `pk`).
  - `src.schemas.CamelModel`.
  - `src.exceptions`: `AppError(status_code, code, message)`, `BadRequest` (400, `bad_request`), `Unauthorized` (401, `unauthorized`), `Forbidden` (403, `forbidden`), `NotFound` (404, `not_found`), `Conflict` (409, `conflict`), `PayloadTooLarge` (413, `payload_too_large`), `register_exception_handlers(app)`. Unknown route → 404 `not_found`. Validation failure → 422 `validation_error` with `issues`. Unhandled → 500 `internal_error`.
  - pytest fixtures: `client` (`httpx.AsyncClient` on `ASGITransport(app)`, base URL `http://test`), `db` (an `AsyncSession` on the test database). Tables are created once per session with `Base.metadata.create_all` and truncated after each test.
  - Postgres at `localhost:5432`, user `app`, password `app`, databases `snipwise` and `snipwise_test`. Redis at `localhost:6379`. MinIO at `localhost:9000` (console `9001`), user `minio`, password `minio12345`, bucket `videos`.

- [ ] **Step 1: Install Docker and free the Redis port**

Install OrbStack (`brew install orbstack`) or Docker Desktop, start it, then run `brew services stop redis`.
Run: `docker version`
Expected: prints Client and Server versions.

- [x] **Step 2: Create the repo and `.gitignore`** (done 2026-10-04 when the folder was set up; no commit yet)

`git init` in `snipwise/`. Ignore: `.env`, `.venv/`, `__pycache__/`, `node_modules/`, `.next/`, `*.mp4`, `*.mov`, `*.wav`, `.DS_Store`.

- [ ] **Step 3: Write `docker-compose.yml` and `docker/postgres-init.sql`**

Services: `postgres` (image `postgres:17`, env `POSTGRES_USER=app`, `POSTGRES_PASSWORD=app`, `POSTGRES_DB=snipwise`, init script mounted to `/docker-entrypoint-initdb.d/`, named volume, healthcheck `pg_isready`), `redis` (`redis:7`), `minio` (`pgsty/minio`, the community fork: MinIO stopped publishing `minio/minio` and `minio/mc` in October 2025; command `server /data --console-address ":9001"`, named volume), `createbucket` (`pgsty/mc`, depends on minio, runs `mc alias set local http://minio:9000 minio minio12345 && mc mb --ignore-existing local/videos`). The init SQL is `CREATE DATABASE snipwise_test;`.

Run: `docker compose up -d && docker compose ps`
Expected: postgres, redis and minio are `running`; createbucket has exited with code 0.

- [ ] **Step 4: Create the backend project**

Run in `backend/`: `uv init --python 3.14`, then
`uv add "fastapi[standard]" "sqlalchemy[asyncio]" asyncpg alembic pydantic-settings pyjwt "pwdlib[argon2]"` (switched from bcrypt on 2026-10-06: Argon2id is the modern default, no 72-byte limit)
`uv add --dev pytest pytest-asyncio ruff`

In `pyproject.toml` set `[tool.fastapi] entrypoint = "src.main:app"` and
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"
```
`.env.example` lists: `ENVIRONMENT=development`, `DATABASE_URL=postgresql+asyncpg://app:app@localhost:5432/snipwise`, `TEST_DATABASE_URL=postgresql+asyncpg://app:app@localhost:5432/snipwise_test`, `REDIS_URL=redis://localhost:6379/0`, `FRONTEND_ORIGIN=http://localhost:3000`, `JWT_SECRET=`, `JWT_REFRESH_SECRET=`. Copy it to `.env` and fill the two secrets with `openssl rand -hex 32`.

- [ ] **Step 5: Write the failing tests**

```python
# tests/test_health.py
async def test_health_returns_ok(client):
    res = await client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

async def test_unknown_route_uses_error_shape(client):
    res = await client.get("/api/nope")
    assert res.status_code == 404
    assert res.json()["code"] == "not_found"
    assert set(res.json()) == {"code", "message"}

async def test_cors_allows_only_frontend_origin(client):
    ok = await client.options("/api/health", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    bad = await client.options("/api/health", headers={"Origin": "http://evil.test", "Access-Control-Request-Method": "GET"})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in bad.headers
```

`conftest.py` must set `os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]` (loaded from `.env`) before importing `src`.

- [ ] **Step 6: Run the tests to see them fail**

Run: `uv run pytest tests/test_health.py -v`
Expected: FAIL, `src.main` does not exist.

- [ ] **Step 7: Write the skeleton**

Copy `config.py`, `database.py`, `models.py`, `schemas.py`, `exceptions.py` and `main.py` from the reference project, then change:
- `exceptions.py`: each `AppError` subclass gets a `code` class attribute, and `_error_response` returns `{"code", "message", **extra}` (drop the `success` key).
- `models.py`: add the naming convention to `Base.metadata`.
- `main.py`: add `CORSMiddleware(allow_origins=[settings.frontend_origin], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])`.
- `config.py`: add the fields listed under Produces.

- [ ] **Step 8: Set up Alembic for async**

Run: `uv run alembic init -t async alembic`. In `env.py` set `target_metadata = Base.metadata`, read the URL from `settings.database_url`, and import every `models.py` module so autogenerate sees the tables (none yet).

- [ ] **Step 9: Run the tests to see them pass**

Run: `uv run pytest -v`
Expected: 3 passed.

- [ ] **Step 10: Commit**

```bash
git add -A && git commit -m "chore: repo, local services and FastAPI skeleton"
```

---

### Task 2: User and refresh-token tables, auth helpers

**Who:** Claude

**Files:**
- Create: `backend/src/users/{__init__,models,schemas}.py`
- Create: `backend/src/auth/{__init__,config,utils,models,exceptions}.py`
- Create: `backend/alembic/versions/<rev>_users_and_refresh_tokens.py`
- Test: `backend/tests/auth/test_utils.py`

**Interfaces:**
- Produces:
  - `users.models.User`: table `users`; `id` (UUID v7 pk), `email` (unique), `password_hash`, `role` (`UserRole` StrEnum `USER`/`ADMIN`, stored with `Enum(UserRole, native_enum=False, length=10)`, default `USER`), `created_at`.
  - `auth.models.RefreshToken`: table `refresh_tokens`; `id` (UUID v7 pk), `user_id` (fk `users.id` ON DELETE CASCADE, indexed), `token_hash` (unique), `expires_at`, `revoked_at` (nullable), `created_at`.
  - `auth.utils` (copied unchanged): `hash_password`, `verify_password`, `create_access_token(user_id, role) -> str`, `create_refresh_token(user_id, role) -> tuple[str, datetime]`, `decode_access_token`, `decode_refresh_token`, `hash_token`.
  - `auth.exceptions`: `InvalidCredentials` (401, `invalid_credentials`, "Invalid email or password"), `EmailAlreadyExists` (409, `email_exists`), `InvalidRefreshToken` (401, `invalid_refresh_token`), `AuthenticationRequired` (401, `unauthorized`), `InvalidAccessToken` (401, `invalid_token`).
  - `users.schemas.UserOut(id, email, role)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/auth/test_utils.py
async def test_password_round_trip():
    h = await hash_password("correct horse")
    assert h != "correct horse"
    assert await verify_password("correct horse", h)
    assert not await verify_password("wrong", h)

def test_access_token_carries_user_and_role():
    uid = uuid.uuid7()
    payload = decode_access_token(create_access_token(uid, "USER"))
    assert payload["userId"] == str(uid) and payload["role"] == "USER"

def test_refresh_token_is_not_accepted_as_access_token():
    token, _ = create_refresh_token(uuid.uuid7(), "USER")
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token)

def test_hash_token_is_stable_sha256():
    assert hash_token("abc") == hashlib.sha256(b"abc").hexdigest()
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/auth/test_utils.py -v`
Expected: FAIL, `src.auth` not found.

- [ ] **Step 3: Copy the helpers and write the models**

Copy `auth/config.py`, `auth/utils.py` and `auth/exceptions.py` from the reference project. In `exceptions.py` add the `code` values above and make `InvalidAccessToken` a 401. Write `User` and `RefreshToken` with the columns above (do not copy the reference models: they map to Prisma's old table names).

- [ ] **Step 4: Create and apply the migration**

Run: `uv run alembic revision --autogenerate -m "users and refresh tokens" && uv run alembic upgrade head`
Expected: `docker compose exec postgres psql -U app snipwise -c '\dt'` lists `users`, `refresh_tokens`, `alembic_version`.

- [ ] **Step 5: Run the tests to see them pass**

Run: `uv run pytest -v`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: user and refresh token tables, auth helpers"
```

---

### Task 3: Auth endpoints and the current-user dependency

**Who:** Nikhil (he built this in Node; this is the same logic in FastAPI)

**Files:**
- Create: `backend/src/auth/{schemas,service,dependencies,router}.py`
- Create: `backend/src/users/{service,router}.py`
- Modify: `backend/src/main.py` (include the two routers under `/api`)
- Test: `backend/tests/auth/test_auth_api.py`, `backend/tests/conftest.py` (add helpers)

**Interfaces:**
- Consumes: Task 2 models, utils and exceptions.
- Produces:
  - Endpoints:
    - `POST /api/auth/signup` body `{email, password}` (password 8 to 128 chars) → 201 `{id, email, role}`.
    - `POST /api/auth/login` body `{email, password}` → 200 `{accessToken, user}` and sets the refresh cookie.
    - `POST /api/auth/refresh` (reads the cookie, no body) → 200 `{accessToken}` and sets a new refresh cookie.
    - `POST /api/auth/logout` (reads the cookie) → 204 and clears the cookie. Always 204, even with no cookie or a bad one.
    - `GET /api/users/me` → 200 `{id, email, role, minutesUsed, minutesLimit}`.
  - Refresh cookie: name `refresh_token`, `HttpOnly`, `SameSite=Lax`, `Path=/api/auth`, `Max-Age` 7 days, `Secure` only when `settings.environment == "production"`.
  - `auth.service`: `signup(db, email, password) -> User`, `login(db, email, password) -> tuple[User, str, str]` (user, access, refresh), `refresh(db, raw_refresh_token) -> tuple[str, str]`, `logout(db, raw_refresh_token | None) -> None`.
  - `auth.dependencies`: `get_current_user` and `CurrentUser = Annotated[User, Depends(get_current_user)]`. Missing header → `AuthenticationRequired`. Bad or expired token → `InvalidAccessToken`.
  - `users.service.minutes_used_this_month(db, user_id) -> float`: returns `0.0` until Task 4 adds projects.
  - Test helpers in `conftest.py`: `async def make_user(client, email="a@test.com", password="password123") -> dict[str, str]` returns `{"Authorization": "Bearer <token>"}`; fixtures `user_headers` (a@test.com) and `other_headers` (b@test.com).

Rules the tests pin:
- Emails are stored and compared as `email.strip().lower()`.
- Unknown email and wrong password return the identical 401 body.
- `refresh` verifies the JWT, finds a row with that hash where `revoked_at IS NULL` and `expires_at > now()`, then in one transaction runs a guarded `UPDATE refresh_tokens SET revoked_at = now() WHERE id = :id AND revoked_at IS NULL`, checks `rowcount == 1` (else `InvalidRefreshToken`), and inserts the new token row. It reads the user's role from the database, not from the old token.

- [ ] **Step 1: Write the failing tests**

```python
# tests/auth/test_auth_api.py
async def test_signup_then_login(client):
    res = await client.post("/api/auth/signup", json={"email": "a@test.com", "password": "password123"})
    assert res.status_code == 201 and "password" not in res.text
    res = await client.post("/api/auth/login", json={"email": "a@test.com", "password": "password123"})
    assert res.status_code == 200 and res.json()["accessToken"]
    cookie = res.headers["set-cookie"]
    assert "refresh_token=" in cookie and "HttpOnly" in cookie and "Path=/api/auth" in cookie
    assert "refreshToken" not in res.json()

async def test_duplicate_email_ignores_case_and_spaces(client):
    await client.post("/api/auth/signup", json={"email": "a@test.com", "password": "password123"})
    res = await client.post("/api/auth/signup", json={"email": " A@Test.com ", "password": "password123"})
    assert res.status_code == 409 and res.json()["code"] == "email_exists"

async def test_wrong_password_and_unknown_email_look_identical(client):
    await client.post("/api/auth/signup", json={"email": "a@test.com", "password": "password123"})
    wrong = await client.post("/api/auth/login", json={"email": "a@test.com", "password": "nope-nope"})
    unknown = await client.post("/api/auth/login", json={"email": "zz@test.com", "password": "nope-nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()

async def test_long_unicode_password_works(client):
    pw = "पासवर्ड-" + "x" * 90
    await client.post("/api/auth/signup", json={"email": "u@test.com", "password": pw})
    res = await client.post("/api/auth/login", json={"email": "u@test.com", "password": pw})
    assert res.status_code == 200

async def test_refresh_rotates_and_old_token_stops_working(client):
    await make_user(client)                      # logs in; the client keeps the cookie
    old = client.cookies.get("refresh_token")
    first = await client.post("/api/auth/refresh")
    assert first.status_code == 200 and client.cookies.get("refresh_token") != old
    client.cookies.set("refresh_token", old, path="/api/auth")
    again = await client.post("/api/auth/refresh")
    assert again.status_code == 401 and again.json()["code"] == "invalid_refresh_token"

async def test_two_refreshes_at_once_only_one_wins(client):
    await make_user(client)
    a, b = await asyncio.gather(client.post("/api/auth/refresh"), client.post("/api/auth/refresh"))
    assert sorted([a.status_code, b.status_code]) == [200, 401]

async def test_logout_revokes_and_is_idempotent(client):
    await make_user(client)
    token = client.cookies.get("refresh_token")
    assert (await client.post("/api/auth/logout")).status_code == 204
    assert (await client.post("/api/auth/logout")).status_code == 204
    client.cookies.set("refresh_token", token, path="/api/auth")
    assert (await client.post("/api/auth/refresh")).status_code == 401

async def test_me_requires_a_valid_token(client, user_headers):
    assert (await client.get("/api/users/me")).status_code == 401
    assert (await client.get("/api/users/me", headers={"Authorization": "Bearer junk"})).json()["code"] == "invalid_token"
    me = await client.get("/api/users/me", headers=user_headers)
    assert me.json()["email"] == "a@test.com" and me.json()["minutesUsed"] == 0 and me.json()["minutesLimit"] == 60
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/auth/test_auth_api.py -v`
Expected: FAIL with 404s (routes do not exist).

- [ ] **Step 3: Write `auth/schemas.py`**

`SignupRequest(email: EmailStr, password: str 8..128)`, `LoginRequest(email: EmailStr, password: str max 128)`, `LoginResponse(access_token: str, user: UserOut)`, `AccessTokenResponse(access_token: str)`.

- [ ] **Step 4: Write `auth/service.py`** with the four functions under Produces and the rules above. Catch `IntegrityError` on signup and raise `EmailAlreadyExists`.

- [ ] **Step 5: Write `auth/dependencies.py`** using `HTTPBearer(auto_error=False)`.

- [ ] **Step 6: Write `auth/router.py` and `users/router.py`**, set and clear the cookie in the router (the service knows nothing about HTTP), and include both routers in `main.py` with `prefix="/api"`.

- [ ] **Step 7: Run the tests to see them pass**

Run: `uv run pytest -v`
Expected: all passed.

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "feat: signup, login, refresh rotation, logout, current user"
```

---

### Task 4: Projects, the status rules and the monthly quota

**Who:** Nikhil

**Files:**
- Create: `backend/src/projects/{__init__,models,schemas,status,service,dependencies,router,exceptions}.py`
- Create: `backend/alembic/versions/<rev>_projects.py`
- Modify: `backend/src/users/service.py`, `backend/src/main.py`, `backend/alembic/env.py` (import the model)
- Test: `backend/tests/projects/test_projects_api.py`, `backend/tests/projects/test_status.py`, `backend/tests/users/test_quota.py`

**Interfaces:**
- Consumes: `CurrentUser`, `DbSession`, `user_headers`, `other_headers`.
- Produces:
  - `projects.models.Project`: table `projects`; `id`, `user_id` (fk `users.id` ON DELETE CASCADE), `title` (str, 1 to 120), `status` (`Enum(ProjectStatus, native_enum=False, length=20)`, default `uploading`), `options` (JSONB), `source_key` (nullable), `source_size_bytes` (BigInteger, nullable), `duration_sec` (Float, nullable), `width`, `height` (Integer, nullable), `fps` (Float, nullable), `files_expire_at` (nullable), `deleted_at` (nullable), `created_at`. Index `ix_projects_user_id_id` on `(user_id, id)`.
  - `projects.status`:
    - `class ProjectStatus(StrEnum)`: `uploading, uploaded, processing, ready_for_review, rendering, done, failed, cancelled, expired`.
    - `ALLOWED: dict[ProjectStatus, frozenset[ProjectStatus]]`: uploading→{uploaded}; uploaded→{processing}; processing→{ready_for_review, failed, cancelled}; ready_for_review→{rendering}; rendering→{done, failed, cancelled}; done→{ready_for_review}; failed→{processing, rendering}; cancelled→{processing, rendering}; expired→{}.
    - `async def transition(db: AsyncSession, project_id: UUID, *, to: ProjectStatus, from_: Iterable[ProjectStatus]) -> bool`: one guarded `UPDATE projects SET status = :to WHERE id = :id AND status IN (:from_) AND deleted_at IS NULL`, returns `rowcount == 1`. Raises `ValueError` if any `from_ → to` pair is not in `ALLOWED`. Does not commit.
  - `projects.schemas`: `ProjectOptions` with six bools, all default `True`: `remove_silences, remove_fillers, keep_best_take, jump_cut_zoom, captions, color_correction`. `ProjectCreate(title: str 1..120, options: ProjectOptions = ProjectOptions())`. `ProjectUpdate(title: str 1..120)`. `ProjectOut(id, title, status, options, duration_sec, width, height, files_expire_at, created_at)`. `ProjectPage(data: list[ProjectOut], next_cursor: UUID | None)`.
  - `projects.dependencies`: `get_owned_project` and `OwnedProject = Annotated[Project, Depends(get_owned_project)]`: loads by path `project_id` where `user_id == current_user.id AND deleted_at IS NULL`, else `ProjectNotFound` (404, `not_found`, "Project not found").
  - Endpoints: `POST /api/projects` → 201; `GET /api/projects?limit=20&cursor=<uuid>` (limit 1 to 100) → `ProjectPage`, newest first (`ORDER BY id DESC`, `id < cursor`, fetch `limit + 1` to compute `nextCursor`); `GET /api/projects/{id}`; `PATCH /api/projects/{id}` (title only); `DELETE /api/projects/{id}` → 204, sets `deleted_at = now()`.
  - `users.service.minutes_used_this_month(db, user_id) -> float`: `SUM(duration_sec) / 60` over the user's projects with `created_at >=` the first instant of the current UTC month, **including deleted ones**; `0.0` when none.

- [ ] **Step 1: Write the failing tests**

```python
# tests/projects/test_projects_api.py
async def test_create_and_get(client, user_headers):
    res = await client.post("/api/projects", json={"title": "Episode 1"}, headers=user_headers)
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "uploading" and body["options"]["removeSilences"] is True
    assert (await client.get(f"/api/projects/{body['id']}", headers=user_headers)).status_code == 200

async def test_other_users_project_is_404(client, user_headers, other_headers):
    pid = (await client.post("/api/projects", json={"title": "Mine"}, headers=user_headers)).json()["id"]
    for call in (client.get, client.delete):
        assert (await call(f"/api/projects/{pid}", headers=other_headers)).status_code == 404
    assert (await client.patch(f"/api/projects/{pid}", json={"title": "x"}, headers=other_headers)).status_code == 404

async def test_list_is_newest_first_and_paginates(client, user_headers):
    ids = [(await client.post("/api/projects", json={"title": f"p{i}"}, headers=user_headers)).json()["id"] for i in range(5)]
    page1 = (await client.get("/api/projects?limit=2", headers=user_headers)).json()
    assert [p["id"] for p in page1["data"]] == ids[::-1][:2] and page1["nextCursor"] == ids[::-1][1]
    page3 = (await client.get(f"/api/projects?limit=2&cursor={ids[1]}", headers=user_headers)).json()
    assert [p["id"] for p in page3["data"]] == [ids[0]] and page3["nextCursor"] is None

async def test_bad_cursor_is_422_and_unknown_cursor_is_empty(client, user_headers):
    assert (await client.get("/api/projects?cursor=abc", headers=user_headers)).status_code == 422
    res = await client.get("/api/projects?cursor=00000000-0000-7000-8000-000000000000", headers=user_headers)
    assert res.status_code == 200 and res.json() == {"data": [], "nextCursor": None}

async def test_deleted_project_is_gone_everywhere(client, user_headers):
    pid = (await client.post("/api/projects", json={"title": "x"}, headers=user_headers)).json()["id"]
    assert (await client.delete(f"/api/projects/{pid}", headers=user_headers)).status_code == 204
    assert (await client.get(f"/api/projects/{pid}", headers=user_headers)).status_code == 404
    assert (await client.patch(f"/api/projects/{pid}", json={"title": "y"}, headers=user_headers)).status_code == 404
    assert (await client.delete(f"/api/projects/{pid}", headers=user_headers)).status_code == 404
    assert (await client.get("/api/projects", headers=user_headers)).json()["data"] == []

async def test_title_is_validated(client, user_headers):
    assert (await client.post("/api/projects", json={"title": ""}, headers=user_headers)).status_code == 422
    assert (await client.post("/api/projects", json={"title": "x" * 121}, headers=user_headers)).status_code == 422
```

```python
# tests/projects/test_status.py
async def test_transition_wins_only_once(db, project):          # `project` fixture: a row with status "uploading"
    assert await transition(db, project.id, to=ProjectStatus.uploaded, from_=[ProjectStatus.uploading]) is True
    assert await transition(db, project.id, to=ProjectStatus.uploaded, from_=[ProjectStatus.uploading]) is False

async def test_transition_rejects_moves_not_in_the_table(db, project):
    with pytest.raises(ValueError):
        await transition(db, project.id, to=ProjectStatus.done, from_=[ProjectStatus.uploading])
```

```python
# tests/users/test_quota.py
async def test_quota_counts_this_month_including_deleted(db, user):
    now = datetime.now(UTC)
    last_month = now.replace(day=1) - timedelta(days=1)
    db.add_all([
        Project(user_id=user.id, title="a", options={}, duration_sec=600, created_at=now),
        Project(user_id=user.id, title="b", options={}, duration_sec=300, created_at=now, deleted_at=now),
        Project(user_id=user.id, title="c", options={}, duration_sec=900, created_at=last_month),
        Project(user_id=user.id, title="d", options={}, duration_sec=None, created_at=now),
    ])
    await db.commit()
    assert await minutes_used_this_month(db, user.id) == 15.0

async def test_quota_is_zero_with_no_projects(db, user):
    assert await minutes_used_this_month(db, user.id) == 0.0
```

Add `user` and `project` fixtures to `conftest.py` that insert rows directly.

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/projects tests/users -v`
Expected: FAIL, modules not found.

- [ ] **Step 3: Write `projects/models.py` and `projects/status.py`, then the migration**

Run: `uv run alembic revision --autogenerate -m "projects" && uv run alembic upgrade head`

- [ ] **Step 4: Write `schemas.py`, `exceptions.py`, `dependencies.py`, `service.py`, `router.py`** per the Interfaces block, and include the router in `main.py`.

- [ ] **Step 5: Replace the stub in `users/service.py`** with the real `minutes_used_this_month`.

- [ ] **Step 6: Run the tests to see them pass**

Run: `uv run pytest -v`
Expected: all passed.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: project CRUD, status rules, monthly quota"
```

---

### Task 5: Frontend login and dashboard

**Who:** Claude

**Files:**
- Create: `frontend/` via `npx create-next-app@latest frontend --typescript --tailwind --app --src-dir --eslint --no-import-alias`
- Create: `frontend/.env.local` with `NEXT_PUBLIC_API_URL=http://localhost:8000/api`
- Create: `frontend/src/lib/api.ts`, `frontend/src/lib/auth-context.tsx`
- Create: `frontend/src/app/(auth)/login/page.tsx`, `frontend/src/app/(auth)/signup/page.tsx`
- Create: `frontend/src/app/(app)/layout.tsx`, `frontend/src/app/(app)/dashboard/page.tsx`

**Interfaces:**
- Consumes: the Task 3 and Task 4 endpoints.
- Produces:
  - `api.ts`: `apiFetch<T>(path: string, init?: RequestInit): Promise<T>`. Keeps the access token in a module variable (never in `localStorage`). Sends `Authorization: Bearer`. On a 401 it calls `POST /auth/refresh` with `credentials: "include"` once, retries the request once, and on a second failure clears the token and redirects to `/login`. Throws `ApiError { status, code, message }` built from the error body. Exports `setAccessToken`, `login`, `signup`, `logout`.
  - `auth-context.tsx`: on load, tries one refresh to restore the session, then exposes `{ user, loading }`.
  - `(app)/layout.tsx`: redirects to `/login` when there is no user; shows the email and a Log out button.
  - Dashboard: project cards (title, status badge, created date), a "Load more" button driven by `nextCursor`, a usage bar reading `minutesUsed` and `minutesLimit` ("23 of 60 minutes used this month"), and a "New project" form with a title field that calls `POST /projects`.

- [ ] **Step 1: Scaffold the app and write `api.ts` and `auth-context.tsx`.**

- [ ] **Step 2: Write the login and signup pages.** Show `ApiError.message` under the form on failure.

- [ ] **Step 3: Write the app layout and dashboard.**

- [ ] **Step 4: Verify the build**

Run in `frontend/`: `npm run lint && npm run build`
Expected: both succeed with no errors.

- [ ] **Step 5: Verify in the browser**

Start the API (`uv run fastapi dev` in `backend/`) and the UI (`npm run dev` in `frontend/`). Check, in order:
1. Sign up, then log in: lands on the dashboard, usage bar reads "0 of 60 minutes".
2. Create two projects: both appear, newest first.
3. Reload the page: still logged in (the refresh cookie restored the session).
4. In DevTools, Application → Cookies: `refresh_token` is HttpOnly. `localStorage` holds no token.
5. Log out, press Back: redirected to `/login`.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: frontend login, signup and dashboard"
```

---

## Done when

- `docker compose up -d`, `uv run fastapi dev` and `npm run dev` give a working login and dashboard.
- `uv run pytest` passes and `uv run ruff check .` is clean.
- Concepts Nikhil can explain: why the refresh token is in an httpOnly cookie and the access token in memory, how the guarded `UPDATE` stops two refreshes both winning, why another user's project is a 404, why cursor pagination beats offset, and why the quota is a `SUM` query.
