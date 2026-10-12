import asyncio
import json
import logging
import signal

from backend.api.schemas import SourceOut
from backend.config import settings
from backend.infrastructure.db import crud
from backend.infrastructure.db.database import async_session
from backend.infrastructure.rag.store import add_file_source, add_text_source
from backend.infrastructure.kafka import producer as mq
from backend.infrastructure.redis.client import get_redis
from backend.infrastructure.redis.shelf import delete_cached_shelves
from backend.infrastructure.redis.space_snapshot import delete_cached_space_snapshot


MAX_RETRY = 1
SOURCE_KEY = "source:{user_id}:{source_id}"
redis = get_redis()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker.source")


async def _process_one(msg: dict):
    user_id = msg["user_id"]
    source_id = msg["source_id"]
    saved_path = msg["saved_path"]
    modality = msg["modality"]
    title = msg["title"]
    created_at = msg["created_at"]
    shelf_id = msg["shelf_id"]

    await redis.set(
        SOURCE_KEY.format(user_id=user_id, source_id=source_id), 
        json.dumps({**msg, "status": "processing"}), 
        ex=settings.source_cache_ttl_seconds
        )
    async with async_session() as session:
        existing = await crud.get_source_by_id(session, source_id)
        if existing:
            data = SourceOut.model_validate(existing).model_dump(mode="json")
            await redis.set(
                SOURCE_KEY.format(user_id=user_id, source_id=source_id), 
                json.dumps({**data, "user_id": user_id, "saved_path": saved_path}), 
                ex=settings.source_cache_ttl_seconds
                )
            return
        if modality == "text" or modality == "url":
            text = msg.get("text", "")
            if not text:
                raise ValueError("text is empty")
            source = await add_text_source(
                session,
                user_id=user_id,
                source_id=source_id,
                saved_path=saved_path,
                modality=modality,
                status = "ready",
                created_at=created_at,
                title=title,
                text=text,
                shelf_id=shelf_id,
            )
        else:
            source = await add_file_source(
                session, 
                user_id=user_id, 
                source_id=source_id, 
                saved_path=saved_path, 
                modality=modality, 
                status = "ready",
                created_at=created_at, 
                title=title,
                shelf_id=shelf_id,
            )
    data = SourceOut.model_validate(source).model_dump(mode="json")
    await redis.set(SOURCE_KEY.format(
        user_id=user_id, source_id=source_id), 
        json.dumps({**data, "user_id": user_id, "saved_path": saved_path}), 
        ex=settings.source_cache_ttl_seconds)
    await delete_cached_space_snapshot(user_id)
    await delete_cached_shelves(user_id)


async def _handle_failure(msg: dict, exc: Exception) -> None:
    retry = int(msg.get("retry", 0)) + 1
    msg["retry"] = retry
    msg["error"] = str(exc)
    if retry >= MAX_RETRY:
        await mq.publish(settings.topic_add_source_dlq, msg)
        user_id, source_id = msg["user_id"], msg["source_id"]
        await redis.set(
            SOURCE_KEY.format(user_id=user_id, source_id=source_id), 
            json.dumps({**msg, "status": "failed"}), 
            ex=settings.source_cache_ttl_seconds)
    else:
        await mq.publish(
            settings.topic_add_source_retry, msg
            )


async def run_kafka() -> None:
    from aiokafka import AIOKafkaConsumer

    consumer = AIOKafkaConsumer(
        settings.topic_add_source,
        settings.topic_add_source_retry,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.source_consumer,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )

    await consumer.start()
    logger.info("source_consumer started")
    stop = asyncio.Event()

    def _stop(*_args):
        stop.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        while not stop.is_set():
            batch = await consumer.getmany(timeout_ms=1000, max_records=50)
            if not batch:
                continue
            for _tp, messages in batch.items():
                for record in messages:
                    raw = record.value or b""
                    try:
                        logger.info("begin to process")
                        msg = json.loads(raw.decode("utf-8"))
                        await _process_one(msg)
                        logger.info("process one successfully")
                    except Exception as exc:
                        logger.exception("process errot %s", exc)
                        try:
                            msg = json.loads(raw.decode("utf-8"))
                        except Exception:
                            msg = {"raw": raw.decode("utf-8", errors="replace")}
                        logger.info("process retry")
                        await _handle_failure(msg, exc)
            await consumer.commit()
    finally:
        await consumer.stop()
        await mq.close_producer()

if __name__ == "__main__":
    asyncio.run(run_kafka())
