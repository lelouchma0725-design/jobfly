"""文件上傳與管理（FR-1b）。附件入 R2，DB 只存元數據（GAP-8）。"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.core.audit import log_audit
from app.core.auth import get_current_user
from app.core.r2 import object_url, presigned_url, upload_bytes
from app.db import get_db
from app.services.parse_service import parse_document

router = APIRouter(prefix="/documents", tags=["documents"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]

MAX_BYTES = 50 * 1024 * 1024  # Supabase Storage 免費層單文件上限
DOC_TYPES = ("resume", "cover_letter", "transcript", "visa", "certificate", "portfolio", "other")
ALLOWED_MIME = {
    "application/pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


@router.post("", status_code=201)
async def upload_document(
    user: CurrentUser,
    db: DB,
    request: Request,
    doc_type: str,
    file: UploadFile = File(...),
) -> dict:
    if doc_type not in DOC_TYPES:
        raise HTTPException(422, f"doc_type 必須是 {DOC_TYPES} 之一")
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(422, f"不支持的文件類型: {file.content_type}")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "文件超過 50MB 上限")

    doc_id = uuid.uuid4()
    ext = ALLOWED_MIME[file.content_type]
    storage_path = f"users/{user['id']}/{doc_id}.{ext}"
    upload_bytes(storage_path, data, file.content_type)

    row = db.execute(
        text(
            """
            INSERT INTO user_documents
              (user_id, doc_type, file_name, storage_path, mime, size_bytes, parse_status)
            VALUES (:uid, :doc_type, :name, :path, :mime, :size, 'pending')
            RETURNING id
            """
        ),
        {
            "uid": user["id"],
            "doc_type": doc_type,
            "name": file.filename or f"{doc_id}.{ext}",
            "path": storage_path,
            "mime": file.content_type,
            "size": len(data),
        },
    ).mappings().one()
    db.commit()
    log_audit(db, user["id"], "document.upload", "user_documents", str(row["id"]),
              {"doc_type": doc_type, "size": len(data)},
              request.client.host if request.client else None)
    return {"id": str(row["id"])}


@router.get("")
def list_documents(user: CurrentUser, db: DB, doc_type: str | None = None) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT id, doc_type, file_name, mime, size_bytes, parse_status, created_at, is_active
            FROM user_documents
            WHERE user_id = :uid AND deleted_at IS NULL
              AND (CAST(:t AS text) IS NULL OR CAST(doc_type AS text) = :t)
            ORDER BY created_at DESC
            """
        ),
        {"uid": user["id"], "t": doc_type},
    ).mappings().all()
    return [
        {
            "id": str(r["id"]),
            "doc_type": r["doc_type"],
            "file_name": r["file_name"],
            "mime": r["mime"],
            "size_bytes": r["size_bytes"],
            "parse_status": r["parse_status"],
            "is_active": r["is_active"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


@router.post("/{doc_id}/parse", status_code=202)
def trigger_parse(user: CurrentUser, db: DB, doc_id: str) -> dict:
    """觸發文檔解析（文本抽取 + LLM 結構化），同步執行。"""
    row = db.execute(
        text(
            "SELECT storage_path, mime FROM user_documents "
            "WHERE id = :did AND user_id = :uid AND deleted_at IS NULL"
        ),
        {"did": doc_id, "uid": user["id"]},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "文件不存在")
    try:
        parse_document(db, doc_id, user["id"], row["storage_path"], row["mime"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"解析失敗: {exc}") from exc
    return {"ok": True}


@router.get("/{doc_id}")
def get_document(user: CurrentUser, db: DB, doc_id: str) -> dict:
    row = db.execute(
        text(
            "SELECT storage_path, file_name, mime, doc_type, parse_status "
            "FROM user_documents WHERE id = :did AND user_id = :uid AND deleted_at IS NULL"
        ),
        {"did": doc_id, "uid": user["id"]},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "文件不存在")
    return {
        "id": doc_id,
        "file_name": row["file_name"],
        "doc_type": row["doc_type"],
        "mime": row["mime"],
        "parse_status": row["parse_status"],
        "url": object_url(row["storage_path"]) if settings.r2_public_base_url
        else presigned_url(row["storage_path"]),
    }


@router.delete("/{doc_id}", status_code=204)
def delete_document(user: CurrentUser, db: DB, doc_id: str, request: Request) -> None:
    row = db.execute(
        text(
            "UPDATE user_documents SET deleted_at = now(), is_active = false "
            "WHERE id = :did AND user_id = :uid AND deleted_at IS NULL RETURNING id"
        ),
        {"did": doc_id, "uid": user["id"]},
    ).first()
    if not row:
        raise HTTPException(404, "文件不存在")
    db.commit()
    log_audit(db, user["id"], "document.delete", "user_documents", doc_id,
              {}, request.client.host if request.client else None)
