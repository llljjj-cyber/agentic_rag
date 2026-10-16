"""Structured JSON logging + request_id context."""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

_request_id: ContextVar[str] = ContextVar("request_id", default="")

_SKIP_ACCESS_PATHS = frozenset({"/health", "/metrics", "/favicon.ico"})


def get_request_id() -> str:
    return _request_id.get()


def set_request_id(value: str) -> None:
    _request_id.set(value)


def ensure_request_id(incoming: str | None = None) -> str:
    rid = (incoming or "").strip() or uuid.uuid4().hex[:16]
    set_request_id(rid)
    return rid


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = get_request_id()
        if rid:
            payload["request_id"] = rid

        for key in (
            "user_id",
            "conv_id",
            "source_id",
            "modality",
            "route",
            "method",
            "status",
            "duration_ms",
            "code",
            "circuit",
            "retry",
            "error",
        ):
            val = getattr(record, key, None)
            if val is not None:
                payload[key] = val

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)

    # Keep noisy libs quieter
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("aiokafka").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def bind_extra(**kwargs: Any) -> dict[str, Any]:
    """Build logging `extra=` dict, dropping Nones."""
    return {k: v for k, v in kwargs.items() if v is not None}


class RequestIdMiddleware:
    """ASGI middleware: assign request_id and emit access log."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        headers = {
            k.decode("latin1").lower(): v.decode("latin1")
            for k, v in scope.get("headers") or []
        }
        rid = ensure_request_id(headers.get("x-request-id"))
        method = scope.get("method") or ""
        t0 = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message.get("status") or 500)
                raw_headers = list(message.get("headers") or [])
                raw_headers.append((b"x-request-id", rid.encode("latin1")))
                message = {**message, "headers": raw_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            if path not in _SKIP_ACCESS_PATHS and not path.startswith("/metrics"):
                duration_ms = round((time.perf_counter() - t0) * 1000, 2)
                get_logger("meridian.access").info(
                    "access",
                    extra=bind_extra(
                        method=method,
                        route=path,
                        status=status_code,
                        duration_ms=duration_ms,
                    ),
                )
