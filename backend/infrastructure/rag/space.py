import math

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from backend.api.schemas import SourceOut
from backend.infrastructure.db import crud
from backend.infrastructure.db.models import ChunkModel, SourceModel



EMBED_MODEL = "bgem3-flag-1024"
DIMENSIONS = 1024

MODALITY_COLORS = {
    "text": "#9fc9a2",
    "url": "#9fbbe0",
    "pdf": "#c08532",
    "txt": "#c0a8dd",
    "query": "#f54e00",
}



def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm < 1e-12:
        return [0.0] * len(vector)
    return [value / norm for value in vector]


def _orthogonalize(vector: list[float], components: list[list[float]]) -> list[float]:
    adjusted = vector[:]
    for component in components:
        projection = _dot(adjusted, component)
        adjusted = [value - projection * component[index] for index, value in enumerate(adjusted)]
    return adjusted


def compute_centroid(vectors: list[list[float]]) -> list[float] | None:
    """chunk 向量求和后 L2 归一化。vectors 为空返回 None。"""
    if not vectors:
        return None
    dim = min(len(vectors[0]), DIMENSIONS)
    acc = [0.0] * dim
    for vec in vectors:
        for i in range(dim):
            acc[i] += vec[i]
    norm = math.sqrt(sum(v * v for v in acc)) or 1.0
    return [v / norm for v in acc]


def _projection_or_origin(source: SourceModel) -> dict[str, float]:
    if source.proj_x is None or source.proj_y is None or source.proj_z is None:
        return {"x": 0.0, "y": 0.0, "z": 0.0}
    return {"x": source.proj_x, "y": source.proj_y, "z": source.proj_z}


def _pca_projection(vectors: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    if not vectors:
        return {}

    ids = list(vectors)
    rows = [vectors[item_id][: DIMENSIONS] for item_id in ids]
    if len(rows) == 1:
        return {ids[0]: {"x": 0.0, "y": 0.0, "z": 0.0}}

    means = [sum(row[index] for row in rows) / len(rows) for index in range(DIMENSIONS)]
    centered = [[row[index] - means[index] for index in range(DIMENSIONS)] for row in rows]
    components: list[list[float]] = []

    for component_index in range(3):
        candidate = [
            math.sin((index + 1) * (component_index + 1) * 0.017)
            + math.cos((index + 1) * (component_index + 2) * 0.013)
            for index in range(DIMENSIONS)
        ]
        candidate = _normalize(_orthogonalize(candidate, components))

        for _ in range(24):
            scores = [_dot(row, candidate) for row in centered]
            next_candidate = [0.0] * DIMENSIONS
            for score, row in zip(scores, centered):
                for index, value in enumerate(row):
                    next_candidate[index] += score * value
            next_candidate = _normalize(_orthogonalize(next_candidate, components))
            if not any(next_candidate):
                break
            candidate = next_candidate

        if not any(candidate):
            candidate = [0.0] * DIMENSIONS
            candidate[min(component_index, DIMENSIONS - 1)] = 1.0
        components.append(candidate)

    raw = {
        item_id: [_dot(row, component) for component in components]
        for item_id, row in zip(ids, centered)
    }
    max_radius = max(
        math.sqrt(values[0] * values[0] + values[1] * values[1] + values[2] * values[2])
        for values in raw.values()
    ) or 1.0
    scale = 2.65 / max_radius
    return {
        item_id: {
            "x": round(values[0] * scale, 4),
            "y": round(values[1] * scale, 4),
            "z": round(values[2] * scale, 4),
        }
        for item_id, values in raw.items()
    }


def _source_point(source: SourceModel, projection: dict[str, float]) -> dict[str, Any]:
    return {
        "id": source.id,
        "source_id": source.id,
        "title": source.title,
        "modality": source.modality,
        "projection": projection,
        "color": MODALITY_COLORS.get(source.modality, "#94a3b8"),
        "preview": source.summary,
    }


async def rebuild_user_space(db: AsyncSession, user_id: str) -> None:
    """入库/删除后：读 centroid → PCA → 写 proj_x/y/z。"""
    sources: list[SourceModel] = await crud.list_sources_by_user_id(db, user_id)
    
    if not sources:
        return

    vectors: dict[str, list[float]] = {}
    for source in sources:
        if source.centroid_vector is not None:
            vec = source.centroid_vector
            
            if hasattr(vec, "tolist"):
                vec = vec.tolist()
            vectors[source.id] = vec[:DIMENSIONS]

    if not vectors:
        return

    projection_map = await run_in_threadpool(_pca_projection, vectors)
    await crud.update_source_projections(db, projection_map)
    await db.commit()


def _source_out_payload(source: SourceModel, shelf_names: dict[str, str]) -> dict[str, Any]:
    data = SourceOut.model_validate(source).model_dump(mode="json")
    data["shelf_name"] = shelf_names.get(source.shelf_id) if source.shelf_id else None
    return data


async def snapshot(db: AsyncSession, user_id: str) -> dict[str, Any]:
    sources: list[SourceModel] = await crud.list_sources_by_user_id(db, user_id)
    shelves = await crud.list_shelves_by_user_id(db, user_id)
    shelf_names = {shelf.id: shelf.name for shelf in shelves}
    points = [
        _source_point(source, _projection_or_origin(source))
        for source in sources
    ]
    return {
        "sources": [_source_out_payload(source, shelf_names) for source in sources],
        "points": points,
        "dimensions": DIMENSIONS,
        "embedding_model": EMBED_MODEL,
        "projection": {
            "method": "pca_3d",
            "basis": "写入资料库时预计算",
        },
    }


async def space_tool(db: AsyncSession, user_id: str) -> dict[str, Any]:
    space = await crud.space_stats(db, user_id)
    return {
        "sources": space["sources"],
        "chunks": space["chunks"],
        "dimensions": DIMENSIONS,
        "embedding_model": EMBED_MODEL,
        "modalities": space["modalities"],
        "chunk_modalities": space["chunk_modalities"],
        "projection": "pca_3d",
    }