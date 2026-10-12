from datetime import datetime
from typing import Any
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import text

from .models import ChunkModel, ConversationModel, MessageModel, ParentDocModel, ShelfModel, SourceModel, Base, UserModel


async def create_chunk(
    db: AsyncSession,
    *,
    id: str,
    source_id: str,
    title: str,
    modality: str,
    chunk_index: int,
    text: str,
    vector: list[float],
    metadata_: dict[str, Any] = None,
    parent_id: str = None
) -> ChunkModel:
    chunk = ChunkModel(
        id=id,
        source_id=source_id,
        parent_id = parent_id,
        title=title,
        modality=modality,
        chunk_index=chunk_index,
        text=text,
        vector=vector,
        metadata_=metadata_ or {},
    )
    db.add(chunk)
    return chunk


async def create_parent_doc(
    db: AsyncSession,
    id: str,
    source_id: str,
    title: str,
    text: str,
    child_count: int,
    metadata: dict | None = None,
) -> ParentDocModel:
    parent_doc = ParentDocModel(
        id=id,
        source_id=source_id,
        title=title,
        text=text,
        child_count=child_count,
        metadata_=metadata
    )
    db.add(parent_doc)
    return parent_doc

async def create_source(
    db: AsyncSession,
    *,
    user_id: str,
    source_id: str, 
    title: str,
    modality: str,
    created_at: str | datetime,
    summary: str,
    shelf_id: str | None = None,
    status: str = "pending",
    saved_path: str | None = None,
    metadata_: dict[str, Any] | None = None,
) -> SourceModel:
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    if shelf_id:
        shelf = await get_shelf(db, shelf_id)
        if not shelf or shelf.user_id != user_id:
            raise ValueError(f"shelf not found: {shelf_id}")
    source = SourceModel(
        user_id=user_id,
        id=source_id,
        shelf_id=shelf_id,
        title=title,
        modality=modality,
        created_at=created_at,
        summary=summary,
        status=status,
        saved_path=saved_path,
        metadata_=metadata_ or {},
    )
    db.add(source)
    await db.flush() 
    return source

async def update_source_title(db: AsyncSession, source: SourceModel, title: str) -> SourceModel:
    source.title = title.strip()
    await db.commit()
    await db.refresh(source)
    return source

async def delete_source(db: AsyncSession, source: SourceModel) -> None:
    await db.delete(source)
    await db.commit()


async def get_source_by_id(db: AsyncSession, source_id: str) -> SourceModel | None:
    result = await db.execute(select(SourceModel).where(SourceModel.id == source_id))
    return result.scalar_one_or_none()


async def chunks_for_source(db: AsyncSession, source: SourceModel) -> list[ChunkModel]:
    result = await db.execute(select(ChunkModel).where(ChunkModel.source_id == source.id))
    return list(result.scalars().all())


async def list_sources(db: AsyncSession) -> list[SourceModel]:
    result = await db.execute(select(SourceModel))
    return list(result.scalars().all())


async def list_sources_by_user_id(db: AsyncSession, user_id: str) -> list[SourceModel]:
    result = await db.execute(select(SourceModel).where(SourceModel.user_id == user_id))
    return list(result.scalars().all())


async def search_best_chunk_per_source(
    db: AsyncSession,
    user_id: str,
    query_vector: list[float],
    top_k: int = 6,
) -> list[tuple[ChunkModel, float, SourceModel]]:
    """每份资料取相似度最高的 1 个 chunk，再按距离排序取 top_k。"""
    distance_expr = ChunkModel.vector.cosine_distance(query_vector)
    ranked = (
        select(
            ChunkModel.id.label("chunk_id"),
            distance_expr.label("distance"),
            func.row_number()
            .over(
                partition_by=ChunkModel.source_id,
                order_by=distance_expr,
            )
            .label("rn"),
        )
        .join(SourceModel, ChunkModel.source_id == SourceModel.id)
        .where(SourceModel.user_id == user_id)
        .subquery()
    )
    stmt = (
        select(ChunkModel, ranked.c.distance, SourceModel)
        .join(ranked, ChunkModel.id == ranked.c.chunk_id)
        .join(SourceModel, ChunkModel.source_id == SourceModel.id)
        .where(ranked.c.rn == 1)
        .order_by(ranked.c.distance)
        .limit(top_k)
    )
    rows = (await db.execute(stmt)).all()
    return [(chunk, float(distance), source) for chunk, distance, source in rows]


async def search_chunks(
    db: AsyncSession,
    user_id: str,
    query_vector: list[float],
    top_k: int = 6,
) -> list[tuple[ChunkModel, float]]:
    distance = ChunkModel.vector.cosine_distance(query_vector)
    result = await db.execute(
        select(ChunkModel)
        .join(ChunkModel.source)
        .where(SourceModel.user_id == user_id)
        .add_columns(distance.label("distance"))
        .order_by(distance)
        .limit(top_k)
    )
    return result.all()


async def get_count_by_user_id(
    db: AsyncSession,
    user_id: str,
    Model: type[SourceModel] | type[ChunkModel],
) -> int:
    if Model is SourceModel:
        stmt = select(func.count(SourceModel.id)).where(SourceModel.user_id == user_id)
    elif Model is ChunkModel:
        stmt = (
            select(func.count(ChunkModel.id))
            .join(SourceModel, ChunkModel.source_id == SourceModel.id)
            .where(SourceModel.user_id == user_id)
        )
    else:
        raise ValueError(f"unsupported model: {Model}")
    result = await db.execute(stmt)
    return result.scalar_one()

async def get_parent_docs_by_ids(
    db: AsyncSession,
    parent_ids: list[str],
) -> dict[str, ParentDocModel]:
    """批量加载 parent 文档，返回 id -> ParentDocModel 映射。"""
    if not parent_ids:
        return {}
    result = await db.execute(
        select(ParentDocModel).where(ParentDocModel.id.in_(parent_ids))
    )
    return {doc.id: doc for doc in result.scalars().all()}


async def count_by_modality(db: AsyncSession, user_id: str, Model: Base) -> dict[str, int]:
    if Model is SourceModel:
        sql = """
            SELECT s.modality, COUNT(*) AS n_modality
            FROM sources s
            WHERE s.user_id = :user_id
            GROUP BY s.modality;
        """
    elif Model is ChunkModel:
        sql = """
            SELECT c.modality, COUNT(*) AS n_modality
            FROM chunks c
            JOIN sources s ON c.source_id = s.id
            WHERE s.user_id = :user_id
            GROUP BY c.modality;
        """
    else:
        raise ValueError(f"unsupported model: {Model}")
    result = await db.execute(text(sql), {"user_id": user_id})
    return {modality: count for modality, count in result.all()}


async def create_shelf(db: AsyncSession, user_id: str, name: str) -> ShelfModel:
    shelf = ShelfModel(user_id=user_id, name=name)
    db.add(shelf)
    await db.flush()
    shelf.source_count = 0
    return shelf

async def get_shelf(db: AsyncSession, shelf_id: str) -> ShelfModel | None:
    result = await db.execute(select(ShelfModel).where(ShelfModel.id == shelf_id))
    return result.scalar_one_or_none()

async def list_shelves_by_user_id(db: AsyncSession, user_id: str) -> list[ShelfModel]:
    q = (
        select(
            ShelfModel,
            func.count(SourceModel.id).label("source_count"),
        )
        .outerjoin(SourceModel, SourceModel.shelf_id == ShelfModel.id)
        .where(ShelfModel.user_id == user_id)
        .group_by(ShelfModel.id)
    )
    rows = (await db.execute(q)).all()
    out = []
    for shelf, count in rows:
        shelf.source_count = count 
        out.append(shelf)
    return out

async def rename_shelf(db: AsyncSession, shelf: ShelfModel, name: str) -> ShelfModel:
    shelf.name = name.strip()
    await db.flush()
    count = await db.scalar(
        select(func.count(SourceModel.id)).where(SourceModel.shelf_id == shelf.id)
    )
    shelf.source_count = count or 0
    return shelf

async def delete_shelf(db: AsyncSession, shelf: ShelfModel) -> None:
    await db.delete(shelf)
    await db.commit()

async def move_source_to_shelf(db: AsyncSession, source: SourceModel, shelf_id: str) -> SourceModel:
    source.shelf_id = shelf_id
    await db.commit()
    await db.refresh(source)
    return source

async def space_stats(db: AsyncSession, user_id: str) -> dict:
    sources = await get_count_by_user_id(db, user_id, SourceModel)
    chunks = await get_count_by_user_id(db, user_id, ChunkModel)
    source_modalities = await count_by_modality(db, user_id, SourceModel)
    chunk_modalities = await count_by_modality(db, user_id, ChunkModel)
    return {
        "sources": sources,
        "chunks": chunks,
        "modalities": source_modalities,
        "chunk_modalities": chunk_modalities,
    }


async def update_source_centroid(
    db: AsyncSession,
    source: SourceModel,
    centroid: list[float],
) -> None:
    source.centroid_vector = centroid
    await db.flush()

    
async def update_source_projections(
    db: AsyncSession,
    projection_map: dict[str, dict[str, float]],
) -> None:
    if not projection_map:
        return
    ids = list(projection_map.keys())
    result = await db.execute(select(SourceModel).where(SourceModel.id.in_(ids)))
    for source in result.scalars().all():
        proj = projection_map.get(source.id)
        if not proj:
            continue
        source.proj_x = proj["x"]
        source.proj_y = proj["y"]
        source.proj_z = proj["z"]
    await db.flush()


async def get_user_by_username(db: AsyncSession, username: str) -> UserModel | None:
    result = await db.execute(select(UserModel).where(UserModel.username == username))
    return result.scalar_one_or_none()


async def create_user(db: AsyncSession, username: str, hashed_password: str) -> UserModel:
    user = UserModel(username=username, hashed_password=hashed_password)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def create_conversation(
    db: AsyncSession,
    *,
    user_id: str,
    title: str = "新对话",
    adk_session_id: str | None = None,
) -> ConversationModel:
    conversation = ConversationModel(
        user_id=user_id,
        adk_session_id=adk_session_id,
        title=title,
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def update_conversation_title(
    db: AsyncSession,
    conv: ConversationModel,
    title: str,
) -> ConversationModel:
    conv.title = title[:100]
    await db.commit()
    await db.refresh(conv)
    return conv

async def get_conversation(
    db: AsyncSession,
    conv_id: int,
) -> ConversationModel | None:
    result = await db.execute(
        select(ConversationModel).where(ConversationModel.id == conv_id)
    )
    return result.scalar_one_or_none()


async def update_conversation_session(
    db: AsyncSession,
    conv: ConversationModel,
    adk_session_id: str,
) -> ConversationModel:
    conv.adk_session_id = adk_session_id
    await db.commit()
    await db.refresh(conv)
    return conv


async def list_conversations_by_user(
    db: AsyncSession,
    user_id: str,
) -> list[ConversationModel]:
    result = await db.execute(
        select(ConversationModel)
        .where(ConversationModel.user_id == user_id)
        .order_by(ConversationModel.created_at.desc())
    )
    return list(result.scalars().all())


async def create_message(
    db: AsyncSession,
    *,
    conv_id: int,
    role: str,
    content: str,
) -> MessageModel:
    message = MessageModel(
        conversation_id=conv_id,
        role=role,
        content=content,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


async def list_messages_by_conversation(
    db: AsyncSession,
    conv_id: int,
    limit: int = 20,
) -> list[MessageModel]:
    result = await db.execute(
        select(MessageModel)
        .where(MessageModel.conversation_id == conv_id)
        .order_by(MessageModel.created_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def delete_conversation(
    db: AsyncSession,
    conversation: ConversationModel,
) -> None:
    # 调用方负责删 ADK session
    await db.delete(conversation)
    await db.commit()

