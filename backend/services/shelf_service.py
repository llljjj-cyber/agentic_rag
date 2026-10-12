from sqlalchemy.exc import IntegrityError

from backend.api.schemas import ShelfResponse
from backend.infrastructure.db import crud
from backend.infrastructure.db.database import async_session
from backend.infrastructure.redis.shelf import delete_cached_shelves, get_cached_shelves
from backend.infrastructure.redis.space_snapshot import delete_cached_space_snapshot


async def list_shelves(user_id: str) -> list[dict]:
    async def loader():
        async with async_session() as session:
            shelves = await crud.list_shelves_by_user_id(session, user_id)
            return shelves

    return await get_cached_shelves(user_id, loader)


async def create_shelf(user_id: str, name: str) -> dict:
    async with async_session() as session:
        try:
            shelf = await crud.create_shelf(session, user_id=user_id, name=name)
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return {"ok": False, "CODE": "SHELF_EXISTS"}
        await delete_cached_shelves(user_id)
        return {
            "ok": True,
            "shelf": ShelfResponse.model_validate(shelf).model_dump(mode="json"),
        }


async def rename_shelf(user_id: str, shelf_id: str, name: str) -> dict:
    async with async_session() as session:
        shelf = await crud.get_shelf(session, shelf_id)
        if not shelf or shelf.user_id != user_id:
            return {"ok": False, "CODE": "SHELF_NOT_FOUND"}
        try:
            await crud.rename_shelf(session, shelf=shelf, name=name)
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return {"ok": False, "CODE": "SHELF_EXISTS"}
        await delete_cached_shelves(user_id)
        await delete_cached_space_snapshot(user_id)
        return {
            "ok": True,
            "shelf": ShelfResponse.model_validate(shelf).model_dump(mode="json"),
        }


async def delete_shelf(user_id: str, shelf_id: str) -> dict:
    async with async_session() as session:
        shelf = await crud.get_shelf(session, shelf_id)
        if not shelf or shelf.user_id != user_id:
            return {"ok": False, "CODE": "SHELF_NOT_FOUND"}
        await crud.delete_shelf(session, shelf=shelf)
        await delete_cached_shelves(user_id)
        await delete_cached_space_snapshot(user_id)
        return {"ok": True, "deleted": shelf_id}
