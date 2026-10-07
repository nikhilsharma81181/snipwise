import time

from redis.exceptions import RedisError

from src.exceptions import TooManyRequests
from src.redis_client import redis_client


# fixed window: one counter per key per minute, redis deletes it when the minute is over
async def check_rate_limit(key: str, limit: int, window_seconds: int = 60) -> None:
    window = int(time.time() // window_seconds)
    redis_key = f"rl:{key}:{window}"

    try:
        count = await redis_client.incr(redis_key)
        if count == 1:
            await redis_client.expire(redis_key, window_seconds)
    except RedisError:
        # redis down: let the request through rather than lock everyone out
        return

    if count > limit:
        raise TooManyRequests()
