from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.infrastructure.db import crud
from backend.infrastructure.db.database import SESSION_SERVICE, get_db
from backend.api.deps import get_current_user, rate_limit_dep
from backend.api.schemas import ConvRenameRequest, Conversation, Message, User
from backend.infrastructure.agent.agent_runtime import APP_NAME


router = APIRouter(prefix="/conversations", tags=["会话"], dependencies=[Depends(rate_limit_dep)])


@router.get("", response_model=list[Conversation])
async def list_conversations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await crud.list_conversations_by_user(db, user.id)

@router.patch("/{conv_id}/title", response_model=Conversation)
async def rename_conversation(
    conv_id: int,
    req: ConvRenameRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await crud.get_conversation(db=db, conv_id=conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail=f"会话{conv_id}不存在")
    if conv.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权修改此会话")
    else:
        return await crud.update_conversation_title(db=db, conv=conv, title=req.title)

@router.get("/{conv_id}/messages", response_model=list[Message])
async def list_messages(
    conv_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await crud.get_conversation(db, conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail=f"会话{conv_id}不存在")
    if conv.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权查看此会话")
    return await crud.list_messages_by_conversation(db, conv_id)


@router.delete("/{conv_id}")
async def delete_conversation(
    conv_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await crud.get_conversation(db, conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail=f"会话{conv_id}不存在")
    if conv.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权删除此会话")

    # 先清 ADK 记忆，再删产品会话
    if conv.adk_session_id and SESSION_SERVICE is not None:
        try:
            await SESSION_SERVICE.delete_session(
                app_name=APP_NAME,
                user_id=user.id,
                session_id=conv.adk_session_id,
            )
        except Exception:
            # session 已不存在时仍允许删 Conversation
            pass

    await crud.delete_conversation(db, conv)
    return {"message": f"会话{conv_id}删除成功"}