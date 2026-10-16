from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from backend.config import settings
from backend.core.logging import RequestIdMiddleware, setup_logging
from backend.infrastructure.db.database import get_db, init_db
from backend.api.schemas import User
from backend.api.routers.auth import router as auth_router
from backend.api.routers.sources import router as sources_router
from backend.api.routers.conversations import router as conversation_router
from backend.api.routers.shelves import router as shelves_router
from backend.api.routers.chat import router as chat_router
from backend.api.deps import get_current_user, rate_limit_dep
from backend.services.snapshot_service import get_space_snapshot

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> None:
    await init_db()
    yield

app = FastAPI(
    title=f"{settings.app_name} · Agentic RAG",
    version="0.1.0",
    lifespan=lifespan)

allowed_origins = [
    origin.strip()
    for origin in settings.allowed_origins.split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestIdMiddleware)


@app.get("/health")
async def health():
    return {"status": "ok"}

    
@app.get("/space", dependencies=[Depends(rate_limit_dep)])
async def space(
    user: User = Depends(get_current_user)):
    return await get_space_snapshot(user.id)


metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

app.include_router(auth_router)
app.include_router(sources_router)
app.include_router(conversation_router)
app.include_router(chat_router)
app.include_router(shelves_router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=settings.port, reload=True)