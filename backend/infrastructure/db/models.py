import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func, Float, UniqueConstraint  # Text 是一个可变长度的文本字段，没有长度限制（不像 String(255)那样有最大字符数），适合存储较长的内容
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

DEFAULT_DIMENSIONS = 1024


def new_id() -> str:
    return uuid.uuid4().hex[:10]


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(12), nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(String(200), nullable=False)

    sources: Mapped[list["SourceModel"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    conversations: Mapped[list["ConversationModel"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    shelves: Mapped[list["ShelfModel"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

class ShelfModel(Base):
    __tablename__ = "shelves"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(16),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_user_shelf_name"),)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["UserModel"] = relationship(back_populates="shelves")
    sources: Mapped[list["SourceModel"]] = relationship(
        back_populates="shelf"
    )

class SourceModel(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(16),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    shelf_id: Mapped[str] = mapped_column(
        String(16),
        ForeignKey("shelves.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    modality: Mapped[str] = mapped_column(String(32), nullable=False)  # text/url/pdf/md/txt/image
    summary: Mapped[str] = mapped_column(Text, default="")
    saved_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    centroid_vector: Mapped[Optional[list[float]]] = mapped_column(
        Vector(DEFAULT_DIMENSIONS), nullable=True
    )
    proj_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    proj_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    proj_z: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["UserModel"] = relationship(back_populates="sources")
    shelf: Mapped["ShelfModel"] = relationship(back_populates="sources")
    chunks: Mapped[list["ChunkModel"]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
    )
    parents: Mapped[list["ParentDocModel"]] = relationship(back_populates="source", cascade="all, delete-orphan")
   
    
class ChunkModel(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        String(16),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("parents.id", ondelete="CASCADE"), nullable=True, index=True
        )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    modality: Mapped[str] = mapped_column(String(32), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, default=1)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    vector: Mapped[list[float]] = mapped_column(Vector(DEFAULT_DIMENSIONS), nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    source: Mapped["SourceModel"] = relationship(back_populates="chunks")
    parent: Mapped[Optional["ParentDocModel"]] = relationship(back_populates="children")


class ParentDocModel(Base):
    __tablename__ = "parents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    child_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    source: Mapped["SourceModel"] = relationship(back_populates="parents")
    children: Mapped[list["ChunkModel"]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )
    
class MessageModel(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    conversation: Mapped["ConversationModel"] = relationship(back_populates="messages")


class ConversationModel(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(16),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    adk_session_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(100), default="新对话")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    messages: Mapped[list["MessageModel"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
    )
    user: Mapped["UserModel"] = relationship(back_populates="conversations")