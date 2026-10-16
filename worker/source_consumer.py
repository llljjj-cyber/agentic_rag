import asyncio
import json
import time
import signal

from backend.api.schemas import SourceOut
from backend.config import settings
from backend.infrastructure.db import crud
from backend.infrastructure.db.database import async_session
from backend.infrastructure.rag.store import add_file_source, add_text_source
from backend.infrastructure.kafka import producer as mq
from backend.infrastructure.redis.add_source import (
    source_cache_doc,
    source_cache_doc_from_out,
    set_source_cache,
)
from backend.infrastructure.redis.shelf import delete_cached_shelves
from backend.infrastructure.redis.space_snapshot import delete_cached_space_snapshot
from backend.infrastructure.metrics.metrics import INGEST_TOTAL, INGEST_DURATION
from backend.core.circuit_breaker import CircuitOpenError
from backend.core.logging import bind_extra, get_logger, set_request_id, setup_logging

MAX_RETRY = 3

setup_logging()
logger = get_logger("worker.source")


def _msg_cache_doc(msg: dict, *, status: str) -> dict:
    return source_cache_doc(
        id=msg["id"],
        user_id=msg["user_id"],
        status=status,
        title=msg.get("title") or "",
        modality=msg.get("modality") or "",
        shelf_id=msg.get("shelf_id"),
        created_at=msg.get("created_at"),
        saved_path=msg.get("saved_path"),
        retry=int(msg.get("retry") or 0),
        error=msg.get("error"),
        text=msg.get("text"),
    )


def _bind_msg_context(msg: dict) -> None:
    rid = msg.get("request_id") or ""
    if rid:
        set_request_id(str(rid))


async def _process_one(msg: dict):
    _bind_msg_context(msg)
    modality = msg.get("modality", "unknown")
    t0 = time.perf_counter()
    source_id = msg.get("id")
    user_id = msg.get("user_id")

    logger.info(
        "ingest start",
        extra=bind_extra(user_id=user_id, source_id=source_id, modality=modality),
    )

    try:
        user_id = msg["user_id"]
        source_id = msg["id"]
        saved_path = msg["saved_path"]
        modality = msg["modality"]
        title = msg["title"]
        created_at = msg["created_at"]
        shelf_id = msg["shelf_id"]

        await set_source_cache(_msg_cache_doc(msg, status="processing"))
        async with async_session() as session:
            existing = await crud.get_source_by_id(session, source_id)
            if existing:
                data = SourceOut.model_validate(existing).model_dump(mode="json")
                await set_source_cache(
                    source_cache_doc_from_out(
                        data,
                        user_id=user_id,
                        saved_path=saved_path,
                    )
                )
                logger.info(
                    "ingest skipped existing",
                    extra=bind_extra(user_id=user_id, source_id=source_id, modality=modality),
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
                    status="ready",
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
                    status="ready",
                    created_at=created_at,
                    title=title,
                    shelf_id=shelf_id,
                )
        data = SourceOut.model_validate(source).model_dump(mode="json")
        # 先失效 space 缓存，再标 ready，避免前端看到 ready 后仍读到旧 /space 快照
        await delete_cached_space_snapshot(user_id)
        await delete_cached_shelves(user_id)
        await set_source_cache(
            source_cache_doc_from_out(
                data,
                user_id=user_id,
                saved_path=saved_path,
            )
        )
        INGEST_TOTAL.labels(modality=modality, result="ok").inc()
        logger.info(
            "ingest done",
            extra=bind_extra(
                user_id=user_id,
                source_id=source_id,
                modality=modality,
                duration_ms=round((time.perf_counter() - t0) * 1000, 2),
            ),
        )
    except CircuitOpenError as exc:
        INGEST_TOTAL.labels(modality=modality, result="circuit_open").inc()
        logger.warning(
            "ingest circuit open",
            extra=bind_extra(
                user_id=user_id,
                source_id=source_id,
                modality=modality,
                error=str(exc),
            ),
        )
        raise
    except Exception as exc:
        INGEST_TOTAL.labels(modality=modality, result="error").inc()
        logger.exception(
            "ingest error",
            extra=bind_extra(
                user_id=user_id,
                source_id=source_id,
                modality=modality,
                error=str(exc),
            ),
        )
        raise
    finally:
        INGEST_DURATION.observe(time.perf_counter() - t0)


async def _handle_failure(msg: dict, exc: Exception) -> None:
    _bind_msg_context(msg)
    retry = int(msg.get("retry", 0)) + 1
    msg["retry"] = retry
    msg["error"] = str(exc)
    if retry >= MAX_RETRY:
        await mq.publish(settings.topic_add_source_dlq, msg)
        if msg.get("id") and msg.get("user_id"):
            await set_source_cache(_msg_cache_doc(msg, status="failed"))
        logger.error(
            "ingest dlq",
            extra=bind_extra(
                user_id=msg.get("user_id"),
                source_id=msg.get("id"),
                modality=msg.get("modality"),
                retry=retry,
                error=str(exc),
            ),
        )
    else:
        await mq.publish(
            settings.topic_add_source_retry, msg
        )
        logger.warning(
            "ingest retry",
            extra=bind_extra(
                user_id=msg.get("user_id"),
                source_id=msg.get("id"),
                modality=msg.get("modality"),
                retry=retry,
                error=str(exc),
            ),
        )


async def run_kafka() -> None:
    from aiokafka import AIOKafkaConsumer
    from prometheus_client import start_http_server
    start_http_server(9100)
    logger.info("prometheus server started")

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
                        msg = json.loads(raw.decode("utf-8"))
                        await _process_one(msg)
                    except Exception as exc:
                        try:
                            msg = json.loads(raw.decode("utf-8"))
                        except Exception:
                            msg = {"raw": raw.decode("utf-8", errors="replace")}
                        await _handle_failure(msg, exc)
            await consumer.commit()
    finally:
        await consumer.stop()
        await mq.close_producer()

if __name__ == "__main__":
    asyncio.run(run_kafka())
