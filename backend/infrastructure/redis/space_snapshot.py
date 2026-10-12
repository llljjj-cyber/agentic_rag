from typing import Callable, Awaitable
import json

from backend.infrastructure.redis.client import get_redis
from backend.config import settings

SPACE_SNAPSHOT_KEY = "space:snapshot:{user_id}"


async def get_cached_space_snapshot(user_id: str, loader: Callable[[], Awaitable[dict]]) -> dict:
    key = SPACE_SNAPSHOT_KEY.format(user_id=user_id)
    redis = get_redis()
    result = await redis.get(key)
    if result:
        return json.loads(result)
    snapshot = await loader()
    await redis.set(key, json.dumps(snapshot), ex=settings.space_snapshot_cache_ttl_seconds)
    return snapshot


async def delete_cached_space_snapshot(user_id: str) -> None:
    key = SPACE_SNAPSHOT_KEY.format(user_id=user_id)
    redis = get_redis()
    await redis.delete(key)