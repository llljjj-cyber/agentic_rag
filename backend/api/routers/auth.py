from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from backend.infrastructure.db import crud
from backend.infrastructure.db.database import get_db
from backend.api.schemas import User, UserCreate, Token
from backend.api.security import verify_password, create_access_token, hash_password

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", response_model=User, status_code=201)
async def create_user(user: UserCreate, db: AsyncSession = Depends(get_db)):
    existing = await crud.get_user_by_username(db, user.username)
    if existing is not None:
        raise HTTPException(status_code=400, detail=f"用户{user.username}已存在")
    hashed = await run_in_threadpool(hash_password, user.password)
    return await crud.create_user(db, user.username, hashed)

@router.post("/login", response_model=Token)
async def login(user: UserCreate, db: AsyncSession = Depends(get_db)) -> Token:
    result = await crud.get_user_by_username(db, user.username)
    ok = False
    if result is not None:
        ok = await run_in_threadpool(
            verify_password, user.password, result.hashed_password
        )
    if result is None or not ok:
        raise HTTPException(status_code=401, detail="账户或密码错误")
    token = create_access_token(data={"sub": result.username})
    return Token(access_token=token)
   
