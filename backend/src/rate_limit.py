import time

from redis.exceptions import RedisError

from src.exceptions import RATE_LIMITED, AppError
from src.redis_client import redis_client


# fixed window: one counter per key per minute, redis deletes it when the minute is over
async def check_rate_limit(key: str, limit: int, window_seconds: int = 60) -> None:
    now = time.time()
    window = int(now // window_seconds)
    redis_key = f"rl:{key}:{window}"

    try:
        count = await redis_client.incr(redis_key)
        if count == 1:
            await redis_client.expire(redis_key, window_seconds)
    except RedisError:
        # redis down: let the request through rather than lock everyone out
        return

    if count > limit:
        # seconds until this window ends and the counter starts again
        seconds = window_seconds - int(now % window_seconds)
        raise AppError(
            RATE_LIMITED,
            params={"seconds": seconds},
            headers={"Retry-After": str(seconds)},
        )
