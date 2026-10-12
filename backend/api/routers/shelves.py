from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps.auth import get_current_user
from backend.services import shelf_service 
from backend.api.schemas import ShelfRenameRequest, ShelfRequest


router = APIRouter(prefix="/shelves", tags=["书架"])

@router.post("")
async def create_shelf(req: ShelfRequest, user=Depends(get_current_user)):
    result = await shelf_service.create_shelf(user.id, req.name)
    if not result["ok"]:
        raise HTTPException(400, detail=result["CODE"])
    return result["shelf"]

@router.get("")
async def get_shelves(user=Depends(get_current_user)):
    return await shelf_service.list_shelves(user.id)

@router.patch("/{shelf_id}")
async def rename_shelf(shelf_id: str, req: ShelfRenameRequest, user=Depends(get_current_user)):
    result = await shelf_service.rename_shelf(user.id, shelf_id, req.name)
    if not result["ok"]:
        raise HTTPException(400, detail=result["CODE"])
    return result["shelf"]

@router.delete("/{shelf_id}")
async def delete_shelf(shelf_id: str, user=Depends(get_current_user)):
    result = await shelf_service.delete_shelf(user.id, shelf_id)
    if not result["ok"]:
        raise HTTPException(400, detail=result["CODE"])
    return {"deleted": result["deleted"]}