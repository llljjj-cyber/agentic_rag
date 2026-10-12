import httpx
from FlagEmbedding import BGEM3FlagModel
from langchain_core.documents import Document
from starlette.concurrency import run_in_threadpool

from backend.config import settings


BATCH_SIZE = 20
API_KEY = settings.siliconflow_api_key
BGE_MODEL_PATH = settings.bge_model_path

_model = None

def get_model():
    global _model
    if _model is None:
        _model = BGEM3FlagModel(BGE_MODEL_PATH,  use_fp16=False)
    return _model

def _doc_embedding(
    documents: list[Document], 
    model: BGEM3FlagModel | None = None,
    batch_size: int = 16, 
    dense: bool = True, 
    sparse: bool = True, 
    colbert: bool = True
    ) -> list[Document]:
    if model is None:
        model = get_model()

    for i in range(0, len(documents), batch_size):
        batch = documents[i: i + batch_size]
        embeddings = model.encode(
            [doc.page_content for doc in batch],
            batch_size=batch_size,
            max_length=2000,
            return_dense=dense,
            return_sparse=sparse,
            return_colbert_vecs=colbert)
        for j, doc in enumerate(batch):
            if dense:
                doc.metadata["dense"] = embeddings["dense_vecs"][j].tolist()
            if sparse:
                doc.metadata["sparse"] = embeddings["lexical_weights"][j]
            if colbert:
                doc.metadata["colbert"] = embeddings["colbert_vecs"][j]
    return documents

def _text_embedding(
    text: str, 
    model: BGEM3FlagModel | None = None, 
    dense: bool = True, 
    sparse: bool = True, 
    colbert: bool = True
    ) -> dict[str, list[float] | None]:
    if model is None:
        model = get_model()
    result = model.encode(
        text, 
        return_dense=dense, 
        return_sparse=sparse, 
        return_colbert_vecs=colbert
        )
    vec = result["dense_vecs"]
    if hasattr(vec, "ndim") and vec.ndim == 2:
        vec = vec[0]
    return {
        "dense": vec.tolist() if dense else None,
        "sparse": result["lexical_weights"] if sparse else None,
        "colbert": result["colbert_vecs"].tolist() if colbert else None
    }

async def _doc_embeddings_with_api(documents: list[Document], batch_size: int = BATCH_SIZE):
    """只支持dense向量"""
    url = "https://api.siliconflow.cn/v1/embeddings"
    
    if not API_KEY:
        raise ValueError("SILICONFLOW_API_KEY is not set")
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    
    for i in range(0, len(documents), batch_size):
        batch = [doc for doc in documents[i: i + batch_size]]
        batch_texts = [doc.page_content for doc in batch]
        payload = {
            "model": "BAAI/bge-m3",
            "input": batch_texts,                 
            "encoding_format": "float",     
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        items = sorted(data["data"], key=lambda x: x["index"])
        vectors = [item["embedding"] for item in items]
        for j, doc in enumerate(batch):
            doc.metadata["dense"] = vectors[j]
            doc.metadata["sparse"] = None
            doc.metadata["colbert"] = None
    return documents

async def _text_embeddings_with_api(text: str):
    """只支持dense向量"""
    url = "https://api.siliconflow.cn/v1/embeddings"
    
    if not API_KEY:
        raise ValueError("SILICONFLOW_API_KEY is not set")
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": "BAAI/bge-m3",
        "input": text,
        "encoding_format": "float",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    return {
        "dense": data["data"][0]["embedding"],
        "sparse":  None,
        "colbert": None
    }
    

async def get_bgem3_doc_embeddings(
    documents: list[Document], 
    dense: bool = True, 
    sparse: bool = True, 
    colbert: bool = True,
    batch_size: int = BATCH_SIZE):
    if API_KEY:
        return await _doc_embeddings_with_api(documents, batch_size)
    return await run_in_threadpool(_doc_embedding, documents, dense=dense, sparse=sparse, colbert=colbert, batch_size=batch_size)

async def get_bgem3_text_embeddings(
    text: str,
    dense: bool = True, 
    sparse: bool = True, 
    colbert: bool = True):
    if API_KEY:
        return await _text_embeddings_with_api(text)
    return await run_in_threadpool(_text_embedding, text, dense=dense, sparse=sparse, colbert=colbert)