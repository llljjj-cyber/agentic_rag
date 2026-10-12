from datetime import datetime, timezone
from pathlib import Path
import uuid
from backend.api.schemas import SourceOut
from backend.config import settings
from backend.infrastructure.db import crud
from backend.infrastructure.db.database import async_session
from backend.infrastructure.kafka import producer as mq
from backend.infrastructure.rag import store
from backend.infrastructure.redis.add_source import cache_get_source, compensate_source_add, source_add
from backend.infrastructure.redis.shelf import delete_cached_shelves
from backend.infrastructure.redis.space_snapshot import delete_cached_space_snapshot


async def auto_add_source(payload: dict) -> dict:
    payload["source_id"] = str(uuid.uuid4().hex[:10])
    payload["retry"] = 0 
    payload["created_at"] = datetime.now(timezone.utc).isoformat()
    modality = payload.get("modality", "")
    if not modality:
        raise ValueError("modality is required")
    try:
        await mq.publish(
            settings.topic_add_source,
            payload,
        )
        result = await source_add(payload)
    except Exception:
        await compensate_source_add(payload["user_id"], payload["source_id"])
        return {"ok": False, "CODE": "KAFKA_ERROR"}
    return {**result}


async def get_total_source(user_id: str, source_id: str) -> dict:
    async def loader():
        async with async_session() as session:
            return await crud.get_source_by_id(session, source_id)

    source = await cache_get_source(user_id, source_id, loader)
    return source


async def delete_total_source(user_id: str, source_id: str) -> dict:
    async with async_session() as session:
        source = await crud.get_source_by_id(session, source_id)
        if not source or source.user_id != user_id:
            return {"ok": False, "CODE": "SOURCE_NOT_FOUND"}
        await compensate_source_add(user_id, source_id)
        removed = await store.remove_source(session, user_id, source_id)
        if not removed:
            return {"ok": False, "CODE": "SOURCE_NOT_FOUND"}
        if source.saved_path:
            Path(source.saved_path).unlink(missing_ok=True)
        await delete_cached_space_snapshot(user_id)
        await delete_cached_shelves(user_id)
        return {"ok": True, "deleted": source_id}


async def update_source_title(user_id: str, source_id: str, title: str) -> dict:
    async with async_session() as session:
        source = await crud.get_source_by_id(session, source_id)
        if not source or source.user_id != user_id:
            return {"ok": False, "CODE": "SOURCE_NOT_FOUND"}
        source.title = title
        await session.commit()
        await compensate_source_add(user_id, source_id)
        await delete_cached_space_snapshot(user_id)
        return {"ok": True, "source": SourceOut.model_validate(source).model_dump(mode="json")}


async def update_source_shelf(user_id: str, source_id: str, shelf_id: str | None) -> dict:
    async with async_session() as session:
        source = await crud.get_source_by_id(session, source_id)
        if not source or source.user_id != user_id:
            return {"ok": False, "CODE": "SOURCE_NOT_FOUND"}
        shelf_name = None
        if shelf_id is not None:
            shelf = await crud.get_shelf(session, shelf_id)
            if not shelf or shelf.user_id != user_id:
                return {"ok": False, "CODE": "SHELF_NOT_FOUND"}
            shelf_name = shelf.name
        source.shelf_id = shelf_id
        await session.commit()
        await compensate_source_add(user_id, source_id)
        await delete_cached_space_snapshot(user_id)
        await delete_cached_shelves(user_id)
        return {
            "ok": True, 
            "source": {
                **SourceOut.model_validate(source).model_dump(mode="json"), 
                "shelf_name": shelf_name
            }
        }