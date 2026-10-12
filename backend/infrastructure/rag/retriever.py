from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.infrastructure.db import crud
from backend.infrastructure.db.models import ChunkModel
from backend.infrastructure.rag.embedding import get_bgem3_text_embeddings


EMBED_MODEL = "bgem3-flag-1024"
DIMENSIONS = 1024

MODALITY_COLORS = {
    "text": "#9fc9a2",
    "url": "#9fbbe0",
    "pdf": "#c08532",
    "txt": "#c0a8dd",
    "query": "#f54e00",
}


async def search_sources(
    db: AsyncSession, 
    user_id: str, 
    query: str, 
    top_k: int = 6,
    dense: bool = True,
    sparse: bool = False,
    colbert: bool = False
) -> dict[str, Any]:
    result = await get_bgem3_text_embeddings(query, dense, sparse, colbert)
    query_vector = result.get("dense") if isinstance(result, dict) else result
    if query_vector is None:
        raise ValueError("Dense vector is required for search")

    rows = await crud.search_best_chunk_per_source(db, user_id, query_vector, top_k)
    matches = [
    {
        "id": source.id,
        "source_id": source.id,
        "title": source.title,
        "modality": source.modality,
        "text": chunk.text,
        "score": round(1 - distance, 4),
        "metadata": {"best_chunk": chunk.id, **chunk.metadata_},
    }
    for chunk, distance, source in rows
    ] 

    return {
        "matches": matches, 
        }


async def search_chunks(
    db: AsyncSession, 
    user_id: str, 
    query: str, 
    top_k: int = 6,
    dense: bool = True,
    sparse: bool = False,
    colbert: bool = False
    ) -> dict[str, Any]:
    query_result = await get_bgem3_text_embeddings(query, dense, sparse, colbert)
    query_vector = query_result.get("dense") if isinstance(query_result, dict) else query_result
    if query_vector is None:
        raise ValueError("Dense vector is required for search")

    result: list[tuple[ChunkModel, float]] = await crud.search_chunks(
        db, user_id, query_vector, top_k
    )

    if not result:
        return {"matches": []}

    parent_ids = list({
        chunk.parent_id for chunk, _ in result if chunk.parent_id
    })
    parent_map = await crud.get_parent_docs_by_ids(db, parent_ids)

    chunk_matches: list[dict[str, Any]] = []
    seen_parent_ids: set[str] = set()
    for chunk, distance in result:
        if chunk.parent_id:
            if chunk.parent_id in seen_parent_ids:
                continue
            seen_parent_ids.add(chunk.parent_id)
            parent = parent_map.get(chunk.parent_id)
            text = parent.text if parent else chunk.text
        else:
            text = chunk.text
        chunk_matches.append({
            "id": chunk.id,
            "source_id": chunk.source_id,
            "title": chunk.title,
            "modality": chunk.modality,
            "text": text,
            "score": round(1 - distance, 4),
            "metadata": {"chunk_id": chunk.id, **chunk.metadata_},
        })
    matches = sorted(chunk_matches, key=lambda item: item["score"], reverse=True)

    return {
        "matches": matches, 
        }


def retrieval_payload(results: dict[str, Any]) -> dict[str, Any]:
    """将检索结果转换为Agentic RAG的payload格式"""
    return {
        "embedding_model": EMBED_MODEL,
        "matches": [
            {
                "citation": match["id"],
                "source": match["title"],
                "modality": match["modality"],
                "similarity": match["score"],
                "evidence": match["text"],
            }
            for match in results["matches"]
        ],
    }
