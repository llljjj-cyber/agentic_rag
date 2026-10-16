import json
from typing import Any, Awaitable, Callable

from backend.api.schemas import SourceOut
from backend.config import settings
from backend.infrastructure.db.models import SourceModel
from backend.infrastructure.redis.client import get_redis


SOURCE_KEY = "source:{user_id}:{id}"


def source_cache_key(user_id: str, source_id: str) -> str:
    return SOURCE_KEY.format(user_id=user_id, id=source_id)


def source_cache_doc(
    *,
    id: str,
    user_id: str,
    status: str,
    title: str = "",
    modality: str = "",
    shelf_id: str | None = None,
    shelf_name: str | None = None,
    summary: str | None = None,
    metadata: dict[str, Any] | None = None,
    chunk_count: int = 0,
    created_at: Any = None,
    saved_path: str | None = None,
    retry: int = 0,
    error: str | None = None,
    text: str | None = None,
    **_extra: Any,
) -> dict[str, Any]:
    """统一 source Redis / 消息侧文档（主键字段为 id）。"""
    doc: dict[str, Any] = {
        "id": id,
        "user_id": user_id,
        "status": status,
        "title": title,
        "modality": modality,
        "shelf_id": shelf_id,
        "shelf_name": shelf_name,
        "summary": summary,
        "metadata": metadata or {},
        "chunk_count": chunk_count,
        "created_at": created_at,
        "saved_path": saved_path,
        "retry": retry,
        "error": error,
    }
    if text is not None:
        doc["text"] = text
    return doc


def source_cache_doc_from_out(
    data: dict[str, Any],
    *,
    user_id: str,
    saved_path: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    return source_cache_doc(
        id=data["id"],
        user_id=user_id,
        status=status or data.get("status") or "ready",
        title=data.get("title") or "",
        modality=data.get("modality") or "",
        shelf_id=data.get("shelf_id"),
        shelf_name=data.get("shelf_name"),
        summary=data.get("summary"),
        metadata=data.get("metadata") or {},
        chunk_count=int(data.get("chunk_count") or 0),
        created_at=data.get("created_at"),
        saved_path=saved_path if saved_path is not None else data.get("saved_path"),
        retry=int(data.get("retry") or 0),
        error=data.get("error"),
        text=data.get("text"),
    )


async def set_source_cache(doc: dict[str, Any]) -> None:
    redis = get_redis()
    key = source_cache_key(doc["user_id"], doc["id"])
    await redis.set(key, json.dumps(doc), ex=settings.source_cache_ttl_seconds)


async def source_add(payload: dict) -> dict:
    try:
        source_id = payload["id"]
        user_id = payload["user_id"]
        doc = source_cache_doc(
            id=source_id,
            user_id=user_id,
            status="pending",
            title=payload.get("title") or "",
            modality=payload.get("modality") or "",
            shelf_id=payload.get("shelf_id"),
            created_at=payload.get("created_at"),
            saved_path=payload.get("saved_path"),
            retry=int(payload.get("retry") or 0),
            text=payload.get("text"),
        )
        await set_source_cache(doc)
        return {"ok": True, **payload, **doc}
    except Exception:
        return {"ok": False, "CODE": "REDIS_ERROR"}


async def compensate_source_add(user_id: str, source_id: str) -> None:
    redis = get_redis()
    await redis.delete(source_cache_key(user_id, source_id))


async def cache_get_source(
    user_id: str,
    source_id: str,
    loader: Callable[[], Awaitable[SourceModel | None]],
) -> dict:
    redis = get_redis()
    result = await redis.get(source_cache_key(user_id, source_id))
    if result:
        return json.loads(result)

    source = await loader()
    if not source or source.user_id != user_id:
        return {}

    data = SourceOut.model_validate(source).model_dump(mode="json")
    doc = source_cache_doc_from_out(
        data,
        user_id=user_id,
        saved_path=source.saved_path,
    )
    await set_source_cache(doc)
    return doc
