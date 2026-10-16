"""
Redis 分布式熔断器（CLOSED → OPEN → HALF_OPEN → CLOSED）

- CLOSED: 正常放行；失败累计达到阈值 → OPEN
- OPEN: 拒绝调用；超过 recovery 后允许 1 个探针进入 HALF_OPEN
- HALF_OPEN: 探针成功 → CLOSED；失败 → OPEN
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import TypeVar

from redis.asyncio import Redis

from backend.config import settings
from backend.core.logging import bind_extra, get_logger
from backend.infrastructure.metrics.metrics import CIRCUIT_OPEN_TOTAL, CIRCUIT_REJECTS, CIRCUIT_STATE
from backend.infrastructure.redis.client import get_redis

T = TypeVar("T")
logger = get_logger(__name__)


class State(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    pass


def _k(name: str, suffix: str) -> str:
    return f"cb:{name}:{suffix}"


async def before_call(redis: Redis, name: str) -> None:
    state = await redis.get(_k(name, "state")) or State.CLOSED.value

    if state == State.CLOSED.value:
        return

    if state == State.OPEN.value:
        opened_at = await redis.get(_k(name, "opened_at"))
        if not opened_at:
            pass
        elif time.time() - float(opened_at) < settings.circuit_recovery_seconds:
            CIRCUIT_REJECTS.labels(name=name).inc()
            raise CircuitOpenError(f"熔断开启: {name}")

        got = await redis.set(
            _k(name, "probe"),
            "1",
            nx=True,
            ex=settings.circuit_recovery_seconds,
        )
        if not got:
            CIRCUIT_REJECTS.labels(name=name).inc()
            raise CircuitOpenError(f"熔断探测中: {name}")
        await redis.set(_k(name, "state"), State.HALF_OPEN.value)
        CIRCUIT_STATE.labels(name=name).set(1)
        return

    if state == State.HALF_OPEN.value:
        CIRCUIT_REJECTS.labels(name=name).inc()
        CIRCUIT_STATE.labels(name=name).set(1)
        raise CircuitOpenError(f"熔断探测中: {name}")


async def on_success(redis: Redis, name: str) -> None:
    pipe = redis.pipeline()
    pipe.set(_k(name, "state"), State.CLOSED.value)
    pipe.delete(_k(name, "fail"), _k(name, "opened_at"), _k(name, "probe"))
    await pipe.execute()
    CIRCUIT_STATE.labels(name=name).set(0)


async def on_failure(redis: Redis, name: str) -> None:
    state = await redis.get(_k(name, "state")) or State.CLOSED.value

    if state == State.HALF_OPEN.value:
        pipe = redis.pipeline()
        pipe.set(_k(name, "state"), State.OPEN.value)
        pipe.set(_k(name, "opened_at"), str(time.time()))
        pipe.delete(_k(name, "probe"), _k(name, "fail"))
        CIRCUIT_OPEN_TOTAL.labels(name=name).inc()
        CIRCUIT_STATE.labels(name=name).set(2)
        await pipe.execute()
        logger.warning(
            "circuit opened",
            extra=bind_extra(circuit=name, error="half_open_probe_failed"),
        )
        return

    fails = await redis.incr(_k(name, "fail"))
    if fails == 1:
        await redis.expire(_k(name, "fail"), settings.circuit_fail_window_seconds)

    if fails >= settings.circuit_failure_threshold:
        pipe = redis.pipeline()
        pipe.set(_k(name, "state"), State.OPEN.value)
        pipe.set(_k(name, "opened_at"), str(time.time()))
        pipe.delete(_k(name, "probe"))
        CIRCUIT_OPEN_TOTAL.labels(name=name).inc()
        CIRCUIT_STATE.labels(name=name).set(2)
        await pipe.execute()
        logger.warning(
            "circuit opened",
            extra=bind_extra(circuit=name, error=f"failures>={settings.circuit_failure_threshold}"),
        )


async def with_circuit_breaker(
    name: str,
    func: Callable[[], Awaitable[T]],
) -> T:
    redis = get_redis()
    await before_call(redis, name)
    try:
        result = await func()
    except Exception:
        await on_failure(redis, name)
        raise
    else:
        await on_success(redis, name)
        return result