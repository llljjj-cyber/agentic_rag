import json
from typing import Any

from aiokafka import AIOKafkaProducer

from backend.config import settings

_producer: AIOKafkaProducer | None = None


async def get_producer() -> AIOKafkaProducer:
    global _producer
    if _producer is None:
        _producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            acks="all",
            linger_ms=5,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
        )
        await _producer.start()
    return _producer


async def publish(topic: str, payload: Any, key: str | None = None) -> None:
    producer = await get_producer()
    await producer.send_and_wait(topic, payload, key=key)


async def close_producer() -> None:
    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None
