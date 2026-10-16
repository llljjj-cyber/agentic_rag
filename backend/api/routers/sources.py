import ipaddress
from pathlib import Path
import socket
from urllib.parse import urlparse
import uuid

from fastapi.responses import FileResponse
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.source_service import auto_add_source, delete_total_source, get_total_source, update_source_shelf, update_source_title

from bs4 import BeautifulSoup
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, Depends
from starlette.concurrency import run_in_threadpool

from backend.config import settings
from backend.services.snapshot_service import get_space_snapshot
from backend.api.schemas import SourceMoveToShelfRequest, SourceOut, SourceRenameRequest, TextSourceRequest, UrlSourceRequest, User
from backend.api.deps import get_current_user


ALLOWED_SUFFIX = {".pdf", ".md", ".txt"}

def _extract_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return " ".join(soup.get_text(" ").split())


def _validate_fetch_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("仅支持 HTTP 与 HTTPS 网址。")

    if settings.allow_private_urls:
        return

    if parsed.hostname.lower() == "localhost":
        raise ValueError("默认禁止抓取 localhost 与内网地址。")

    try:
        address_info = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"无法解析网址主机：{parsed.hostname}") from exc

    for item in address_info:
        address = ipaddress.ip_address(item[4][0])
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
            raise ValueError("默认禁止抓取 localhost 与内网地址。")

router = APIRouter(prefix="/sources",tags=["资源管理"])


@router.post("/text")
async def add_text_source(
    req: TextSourceRequest, 
    user: User = Depends(get_current_user)):
    try:
        text = req.text.strip()
        if not text:
            raise HTTPException(400, "text is empty")
        payload = {
            "user_id": user.id,
            "saved_path": None,
            "modality": req.modality,
            "title": req.title,
            "text": text,
            "shelf_id": req.shelf_id,
        }
        result = await auto_add_source(payload)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    if result["ok"]:
        source_out = SourceOut(
            id=result["id"],
            title=result["title"],
            modality=result["modality"],
            shelf_id=result["shelf_id"],
            status=result["status"],
            created_at=result["created_at"],
        )
        return {"source": SourceOut.model_validate(source_out)}
    else:
        raise HTTPException(500, detail=result)


@router.post("/url")
async def add_url_source(
    req: UrlSourceRequest,
    user: User = Depends(get_current_user)
    ):
    try:
        url = str(req.url)
        await run_in_threadpool(_validate_fetch_url, url)
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
        text = _extract_text_from_html(response.text)
        text = text.strip()
        if not text:
            raise HTTPException(400, "text is empty")
        title = req.title or url.replace("https://", "").replace("http://", "")[:80]
        payload = {
            "user_id": user.id,
            "saved_path": None,
            "modality": "url",
            "title": title,
            "text": text[:12000],
            "shelf_id": req.shelf_id,
        }
        result = await auto_add_source(payload)
        if result["ok"]:
            source_out = SourceOut(
                id=result["id"],
                title=result["title"],
                modality=result["modality"],
                shelf_id=result["shelf_id"],
                status=result["status"],
                created_at=result["created_at"],
            )
            return {"source": SourceOut.model_validate(source_out)}
        else:
            raise HTTPException(500, detail=result)
    except Exception as exc:
        raise HTTPException(400, f"无法入库该网址：{exc}") from exc
    

@router.post("/file")
async def add_file_source(
    user: User = Depends(get_current_user),
    file: UploadFile = File(...),
    title: str | None = Form(None),
    shelf_id: str | None = Form(None),
):
    suffix = Path(file.filename or "").suffix.lower()
    title = title or file.filename or ""
    if suffix not in ALLOWED_SUFFIX:
        raise HTTPException(400, f"仅支持 {', '.join(ALLOWED_SUFFIX)}")
    
    upload_dir = (
        Path(__file__).resolve().parents[2]
        / "infrastructure"
        / "rag"
        / "temp"
        / "uploads"
    )
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}{suffix}"
    saved_path = upload_dir / safe_name

    try:
        content = await file.read()
        if not content:
            raise HTTPException(400, "文件为空")
        if len(content) > 5 * 1024 * 1024:
            raise HTTPException(400, "文件大小上限为 5 MB，请上传更小的文件。")
        saved_path.write_bytes(content)
        modality = suffix[1:]  # pdf / md / txt
        payload = {
            "user_id": user.id,
            "saved_path": str(saved_path),
            "modality": modality,
            "title": title,
            "shelf_id": shelf_id,
        }
        result = await auto_add_source(payload)
    except Exception as exc:
        Path(saved_path).unlink(missing_ok=True)
        raise HTTPException(400, str(exc)) from exc
    
    if result["ok"]:
        source_out = SourceOut(
            id=result["id"],
            title=title,
            modality=modality,
            shelf_id=shelf_id,
            status=result["status"],
            created_at=result["created_at"],
        )
        return {"source": source_out}
    else:
        raise HTTPException(500, detail=result)


@router.get("/{source_id}/detail")
async def get_source_detail(
    source_id: str,
    user: User = Depends(get_current_user)
):
    source = await get_total_source(user.id, source_id)
    if not source or source.get("user_id", "") != user.id:
        raise HTTPException(404, detail="source 不存在")
    status = source.get("status", "")
    if not status or status == "failed":
        raise HTTPException(500, detail="source 解析失败")
    elif status == "pending" or status == "processing":
        return {"status": status}
    else:
        return {"source": source}


@router.get("/{source_id}/file")
async def get_source_file(
    source_id: str,
    user: User = Depends(get_current_user)
):
    source = await get_total_source(user.id, source_id)
    if not source:
        raise HTTPException(404, "未找到该资料。")
    if source.get("modality", "") not in ["pdf", "md", "txt"]:
        raise HTTPException(400, "不支持该类型文件。")
    if not source.get("saved_path", ""):
        raise HTTPException(404, "未找到该文件路径。")
    if not Path(source.get("saved_path", "")).exists():
        raise HTTPException(404, "未找到该文件。")
    ext = Path(source.get("saved_path", "")).suffix
    filename = f'{source.get("title", "")}{ext}'
    media_type = "text/markdown" if ext == ".md" else "application/pdf" if ext == ".pdf" else "text/plain"
    return FileResponse(source.get("saved_path"), filename=filename, media_type=media_type)

@router.patch("/{source_id}/title")
async def rename_source(
    source_id: str,
    req: SourceRenameRequest,
    user: User = Depends(get_current_user)
):
    result = await update_source_title(user.id, source_id, req.title)
    if not result["ok"]:
        raise HTTPException(404, detail=result["CODE"])
    return {"source": result["source"]}

@router.patch("/{source_id}/shelf")
async def move_source_to_shelf(
    source_id: str,
    req: SourceMoveToShelfRequest,
    user: User = Depends(get_current_user)
):
    result = await update_source_shelf(user.id, source_id, req.shelf_id)
    if not result["ok"]:
        raise HTTPException(404, detail=result["CODE"])
    return {"source": result["source"]}

@router.delete("/{source_id}")
async def delete_source(
    source_id: str, 
    user: User=Depends(get_current_user)):
    result = await delete_total_source(user.id, source_id)
    if not result["ok"]:
        raise HTTPException(404, detail=result["CODE"])
    space = await get_space_snapshot(user.id)
    return {"deleted": result["deleted"], "space": space}


