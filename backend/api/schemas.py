from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

class TextSourceRequest(BaseModel):
    title: str
    text: str
    modality: Literal["text"] = "text"
    shelf_id: str | None = None

class UrlSourceRequest(BaseModel):
    url: HttpUrl
    title: Optional[str] = None
    shelf_id: str | None = None

class AskRequest(BaseModel):
    question: str
    session_id: str | None = None
    top_k: int = Field(6, ge=1, le=12)


class UserCreate(BaseModel):
    """创建用户：需要用户名和密码"""

    username: str = Field(..., min_length=1, max_length=12, examples=["ljlkjj"])
    password: str = Field(..., min_length=6, max_length=12, examples=["SIUDUJODFHJ"])

class User(BaseModel):
    """返回给客户端用户信息"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str

class ShelfRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=20)

class ShelfResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    source_count: int = 0
    created_at: datetime

class ShelfRenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=20)

class SourceMoveToShelfRequest(BaseModel):
    shelf_id: str | None = None

class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str 
    modality: str
    summary: str | None = None
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias="metadata_",
    )
    status: str
    shelf_id: str | None = None
    shelf_name: str | None = None 
    chunk_count: int = 0
    created_at: datetime

class SourceRenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=20)

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class Conversation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    created_at: datetime

class ConvRenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)

class Message(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    conv_id: int | None = None

    
class ChatResponse(BaseModel):
    reply: str
    conv_id: int