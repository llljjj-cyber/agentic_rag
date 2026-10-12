from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from google.genai import types as genai_types
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.infrastructure.rag.retriever import search_sources, search_chunks
from backend.infrastructure.rag.retriever import retrieval_payload
from backend.infrastructure.rag.space import space_tool
from backend.infrastructure.db.database import SESSION_SERVICE

SETUP_ERROR = ""
try:
    from google.adk.agents.run_config import RunConfig, StreamingMode
    from google.adk.runners import Runner
    from backend.infrastructure.agent.agent import build_agent

    ADK_AVAILABLE = bool(settings.api_key)
except Exception:
    Runner = None  
    RunConfig = None  
    StreamingMode = None  
    build_agent = None  
    ADK_AVAILABLE = False
    SETUP_ERROR = "无法导入 Google ADK。请安装依赖并设置 API_KEY。"

if not settings.api_key:
    SETUP_ERROR = "需要设置 API_KEY。"

APP_NAME = "multimodal_agentic_rag"


def _event_text(event: Any) -> str:
    if not getattr(event, "content", None) or not event.content.parts:
        return ""
    return "".join(
        getattr(part, "text", None) or ""
        for part in event.content.parts if not getattr(part, "thought", False)
    )


def _require_adk() -> None:
    if not ADK_AVAILABLE or Runner is None or build_agent is None:
        raise HTTPException(503, SETUP_ERROR or "Google ADK 不可用。")
    if SESSION_SERVICE is None:
        raise HTTPException(503, "SessionService 未初始化")


async def ensure_adk_session(user_id: str, adk_session_id: str | None):
    """有则取，无则建。供 Conversation.adk_session_id 绑定。"""
    _require_adk()
    if adk_session_id:
        session = await SESSION_SERVICE.get_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=adk_session_id,
        )
        if session is not None:
            return session
        # 库里有 id 但 ADK 丢了：重建，调用方再写回 conv
    return await SESSION_SERVICE.create_session(
        app_name=APP_NAME,
        user_id=user_id,
    )


@dataclass
class AgentRunState:
    trace: list[dict] = field(default_factory=list)
    last_retrieval: dict[str, Any] | None = None


def build_runner(
    db: AsyncSession,
    user_id: str,
) -> tuple[Any, AgentRunState]:
    """每次请求新建 Agent+Tools+Runner（闭包要带上本次 db/user）。"""
    _require_adk()
    state = AgentRunState()

    async def retrieve_relevant_sources(query: str, top_k: int = 6) -> dict:
        results = await search_sources(db, user_id, query, top_k)
        state.last_retrieval = results
        state.trace.append({
            "agent": "检索资料,粗颗粒度检索",
            "status": "complete",
            "detail": f"已检索到 {len(results['matches'])} 条资料（query={query!r}）",
        })
        return retrieval_payload(results)

    async def retrieve_relevant_chunks(query: str, top_k: int = 6) -> dict:
        results = await search_chunks(db, user_id, query, top_k)
        state.last_retrieval = results
        state.trace.append({
            "agent": "检索证据,细颗粒度检索",
            "status": "complete",
            "detail": f"已检索到 {len(results['matches'])} 条证据（query={query!r}）",
        })
        return retrieval_payload(results)
        
    async def inspect_embedding_space() -> dict:
        space = await space_tool(db, user_id)
        state.trace.append({
            "agent": "空间检查",
            "status": "complete",
            "detail": (
                f"{space['sources']} 份资料，{space['chunks']} 个分块，"
                f"{space['dimensions']} 维"
            ),
        })
        return space

    agent = build_agent([retrieve_relevant_sources, retrieve_relevant_chunks, inspect_embedding_space])
    runner = Runner(
        agent=agent,
        app_name=APP_NAME,
        session_service=SESSION_SERVICE,
    )
    return runner, state


async def stream_agent(
    *,
    runner: Any,
    user_id: str,
    session_id: str,
    question: str,
    streaming: bool = True,
) -> AsyncIterator[Any]:
    content = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=question)],
    )
    run_config = None
    if streaming and RunConfig is not None and StreamingMode is not None:
        run_config = RunConfig(streaming_mode=StreamingMode.SSE)

    kwargs: dict[str, Any] = {
        "user_id": user_id,
        "session_id": session_id,
        "new_message": content,
    }
    if run_config is not None:
        kwargs["run_config"] = run_config

    async for event in runner.run_async(**kwargs):
        yield event
