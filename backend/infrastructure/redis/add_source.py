import json
from typing import Awaitable, Callable
from backend.api.schemas import SourceOut
from backend.config import settings
from backend.infrastructure.db.models import SourceModel
from backend.infrastructure.redis.client import get_redis


SOURCE_KEY = "source:{user_id}:{source_id}"


async def source_add(payload: dict) -> dict:
    try:
        redis = get_redis()
        user_id = payload.get("user_id", "")
        source_id = payload.get("source_id")
        source_key = SOURCE_KEY.format(user_id=user_id, source_id=source_id)
        payload["status"] = "pending"
        await redis.set(source_key, json.dumps(payload), ex=settings.source_cache_ttl_seconds)
        return {"ok": True, **payload}
    except:
        return {"ok": False, "CODE": "REDIS_ERROR"}


async def compensate_source_add(user_id: str, source_id: str) -> None:
    redis = get_redis()
    source_key = SOURCE_KEY.format(user_id=user_id, source_id=source_id)
    await redis.delete(source_key)


async def cache_get_source(
    user_id: str,
    source_id: str,
    loader: Callable[[], Awaitable[SourceModel | None]],
) -> dict:
    redis = get_redis()
    source_key = SOURCE_KEY.format(user_id=user_id, source_id=source_id)
    result = await redis.get(source_key)
    if result:
        return json.loads(result)

    source = await loader()
    if not source or source.user_id != user_id:
        return {}

    data = SourceOut.model_validate(source).model_dump(mode="json")
    data["user_id"] = user_id
    data["saved_path"] = source.saved_path
    await redis.set(source_key, json.dumps(data), ex=settings.source_cache_ttl_seconds)
    return data