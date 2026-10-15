"""崗位瀏覽與手動採集端點（FR-3a）。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.collectors.pipeline import collect_for_user
from app.core.auth import get_current_user
from app.db import get_db

router = APIRouter(prefix="/jobs", tags=["jobs"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]


@router.get("")
def list_jobs(
    user: CurrentUser, db: DB, q: str | None = None, company: str | None = None,
    limit: int = 100, offset: int = 0,
) -> dict:
    limit = min(max(limit, 1), 200)
    rows = db.execute(
        text(
            """
            SELECT p.id, p.company_name, p.title, p.location, p.department, p.source,
                   p.apply_url, p.first_seen_at, p.posted_at,
                   m.match_score, m.status AS match_status, m.id AS match_id
            FROM job_postings p
            LEFT JOIN job_matches m ON m.posting_id = p.id AND m.user_id = :uid
            WHERE p.is_active = true
              AND (:q IS NULL OR p.title ILIKE '%'||:q||'%' OR p.description_text ILIKE '%'||:q||'%')
              AND (:co IS NULL OR p.company_name ILIKE '%'||:co||'%')
            ORDER BY p.first_seen_at DESC
            LIMIT :lim OFFSET :off
            """
        ),
        {"uid": user["id"], "q": q, "co": company, "lim": limit, "off": offset},
    ).mappings().all()
    return {
        "items": [
            {
                "id": str(r["id"]),
                "company_name": r["company_name"],
                "title": r["title"],
                "location": r["location"],
                "department": r["department"],
                "source": r["source"],
                "apply_url": r["apply_url"],
                "first_seen_at": r["first_seen_at"].isoformat(),
                "posted_at": r["posted_at"].isoformat() if r["posted_at"] else None,
                "match_score": r["match_score"],
                "match_status": r["match_status"],
                "match_id": str(r["match_id"]) if r["match_id"] else None,
            }
            for r in rows
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/{posting_id}")
def get_job(user: CurrentUser, db: DB, posting_id: str) -> dict:
    row = db.execute(
        text(
            """
            SELECT p.*, m.match_score, m.reasons, m.hard_failures, m.status AS match_status
            FROM job_postings p
            LEFT JOIN job_matches m ON m.posting_id = p.id AND m.user_id = :uid
            WHERE p.id = :pid
            """
        ),
        {"uid": user["id"], "pid": posting_id},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "崗位不存在")
    return {
        "id": str(row["id"]),
        "company_name": row["company_name"],
        "title": row["title"],
        "location": row["location"],
        "department": row["department"],
        "source": row["source"],
        "apply_url": row["apply_url"],
        "description_text": row["description_text"],
        "first_seen_at": row["first_seen_at"].isoformat(),
        "match_score": row["match_score"],
        "match_status": row["match_status"],
        "reasons": row["reasons"] or [],
        "hard_failures": row["hard_failures"] or [],
    }


@router.post("/collect/run", status_code=202)
def run_collect(user: CurrentUser, db: DB) -> dict:
    """手動觸發：對當前用戶的關注公司立即採集 + 匹配。"""
    try:
        report = collect_for_user(db, user["id"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"採集失敗: {exc}") from exc
    return report
