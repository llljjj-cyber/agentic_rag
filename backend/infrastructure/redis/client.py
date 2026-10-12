from redis.asyncio import ConnectionPool, Redis

from backend.config import settings

_pool: ConnectionPool | None = None
_redis: Redis | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(
            settings.redis_url,
            max_connections=100,
            decode_responses=True,
        )
    return _pool


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis(connection_pool=get_pool())
    return _redis


async def close_redis() -> None:
    global _redis, _pool
    if _redis is not None:
        await _redis.aclose()
        _redis = None
    if _pool is not None:
        await _pool.disconnect()
        _pool = None
