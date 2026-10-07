import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.exceptions import RedisError
from sqlalchemy import text

from src.auth.router import router as auth_router
from src.config import settings
from src.database import engine
from src.exceptions import register_exception_handlers
from src.redis_client import redis_client
from src.users.router import router as users_router

START_TIME = time.monotonic()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
        print("db connected")

    # redis is only for rate limits, so the app still starts without it (fail open)
    try:
        await redis_client.ping()
        print("redis connected")
    except RedisError:
        print("redis not reachable, rate limits are off")

    yield

    await redis_client.aclose()
    await engine.dispose()


app = FastAPI(title="Snipwise API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(auth_router, prefix="/api")
app.include_router(users_router, prefix="/api")


@app.get("/api/health", tags=["health"])
async def health():
    return {"status": "ok", "uptime": round(time.monotonic() - START_TIME, 1)}
