from typing import Awaitable, Callable
import json

from backend.config import settings
from backend.infrastructure.db.models import ShelfModel
from backend.infrastructure.redis.add_source import SOURCE_KEY
from backend.infrastructure.redis.client import get_redis
from backend.api.schemas import ShelfResponse
from backend.infrastructure.redis.space_snapshot import SPACE_SNAPSHOT_KEY

SHELVES_KEY = "shelves:{user_id}"


async def get_cached_shelves(
    user_id: str,
    loader: Callable[[], Awaitable[list[ShelfModel]]],
) -> list[dict]:
    key = SHELVES_KEY.format(user_id=user_id)
    redis = get_redis()
    result = await redis.get(key)
    if result:
        return json.loads(result)
    shelves = await loader()
    data = [ShelfResponse.model_validate(shelf).model_dump(mode="json") for shelf in shelves]
    await redis.set(key, json.dumps(data), ex=settings.shelf_cache_ttl_seconds)
    return data


async def delete_cached_shelves(user_id: str) -> None:
    key = SHELVES_KEY.format(user_id=user_id)
    redis = get_redis()
    await redis.delete(key)


async def invalidate_shelf_related_caches(user_id: str, source_ids: list[str]) -> None:
    redis = get_redis()
    pipe = redis.pipeline()
    source_keys = [
        SOURCE_KEY.format(user_id=user_id, id=sid)
        for sid in source_ids
        if sid
    ]
    pipe.delete(SHELVES_KEY.format(user_id=user_id))
    if source_keys:
        pipe.delete(*source_keys)
    pipe.delete(SPACE_SNAPSHOT_KEY.format(user_id=user_id))
    await pipe.execute()

