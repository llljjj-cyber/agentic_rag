from backend.infrastructure.db.database import async_session
from backend.infrastructure.redis.space_snapshot import get_cached_space_snapshot
from backend.infrastructure.rag.space import snapshot

async def get_space_snapshot(user_id: str) -> dict:
    async def loader():
        async with async_session() as session:
            return await snapshot(session, user_id)

    return await get_cached_space_snapshot(user_id, loader)


