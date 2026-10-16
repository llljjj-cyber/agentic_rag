from fastapi import Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt, JWTError 

from backend.infrastructure.db.database import get_db
from backend.infrastructure.db import crud
from backend.api.security import ALGORITHM, SECRET_KEY
from backend.api.schemas import User
from backend.infrastructure.redis.rate_limit import check_rate_limit


security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)) -> User:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str | None = payload.get('sub')
        if username is None:
            raise HTTPException(status_code=401, detail="无效的token")
    except JWTError:
        raise HTTPException(status_code=401, detail="无效的token")
    
    db_user = await crud.get_user_by_username(db, username)
    if db_user is None: 
        raise HTTPException(status_code=401, detail="无效的token")
    
    return User.model_validate(db_user)

def get_file_path(file_path: str = Query(description="文件路径")) -> str:
    return file_path

async def rate_limit_dep(user: User = Depends(get_current_user)) -> None:
    await check_rate_limit(user.id)
