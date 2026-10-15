"""投遞記錄與觸發端點（FR-3b/3c）。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db import get_db
from app.services.apply_engine import (
    create_applications_from_matches,
    process_queue,
    run_application,
)

router = APIRouter(prefix="/applications", tags=["applications"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]


@router.get("")
def list_applications(user: CurrentUser, db: DB, status: str | None = None) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT a.id, a.status, a.status_reason, a.attempts_count, a.next_retry_at,
                   a.submitted_at, a.external_ref, a.created_at,
                   p.company_name, p.title, p.location, p.apply_url, p.source,
                   m.match_score, rv.id AS resume_version_id
            FROM applications a
            JOIN job_postings p ON p.id = a.posting_id
            LEFT JOIN job_matches m ON m.id = a.match_id
            LEFT JOIN resume_versions rv ON rv.id = a.resume_version_id
            WHERE a.user_id = :uid AND (CAST(:st AS text) IS NULL OR a.status = :st)
            ORDER BY a.created_at DESC LIMIT 200
            """
        ),
        {"uid": user["id"], "st": status},
    ).mappings().all()
    return [
        {
            "id": str(r["id"]),
            "status": r["status"],
            "status_reason": r["status_reason"],
            "attempts_count": r["attempts_count"],
            "next_retry_at": r["next_retry_at"].isoformat() if r["next_retry_at"] else None,
            "submitted_at": r["submitted_at"].isoformat() if r["submitted_at"] else None,
            "external_ref": r["external_ref"],
            "created_at": r["created_at"].isoformat(),
            "company_name": r["company_name"],
            "title": r["title"],
            "location": r["location"],
            "apply_url": r["apply_url"],
            "source": r["source"],
            "match_score": r["match_score"],
            "resume_version_id": str(r["resume_version_id"]) if r["resume_version_id"] else None,
        }
        for r in rows
    ]


@router.post("/run", status_code=202)
def run_now(user: CurrentUser, db: DB) -> dict:
    """手動觸發：按當前設置從匹配結果生成投遞隊列並立即處理。"""
    created = create_applications_from_matches(db, user["id"])
    processed = process_queue(db, user_id=user["id"])
    return {"created": created, "processed": processed}


@router.post("/{application_id}/retry", status_code=202)
def retry_application(user: CurrentUser, db: DB, application_id: str) -> dict:
    row = db.execute(
        text("SELECT status FROM applications WHERE id=:id AND user_id=:uid"),
        {"id": application_id, "uid": user["id"]},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "投遞記錄不存在")
    if row["status"] in ("submitted", "in_progress"):
        return {"skipped": row["status"]}
    out = run_application(db, application_id, force=True)
    return out


@router.post("/{application_id}/abort", status_code=200)
def abort_application(user: CurrentUser, db: DB, application_id: str) -> dict:
    row = db.execute(
        text(
            "UPDATE applications SET status='aborted', status_reason='用戶手動取消', updated_at=now() "
            "WHERE id=:id AND user_id=:uid AND status NOT IN ('submitted','aborted') RETURNING id"
        ),
        {"id": application_id, "uid": user["id"]},
    ).first()
    if not row:
        raise HTTPException(404, "投遞記錄不存在或已結束")
    db.commit()
    return {"ok": True}
