import redis.asyncio as redis

from src.config import settings

redis_client = redis.from_url(str(settings.redis_url), decode_responses=True)
