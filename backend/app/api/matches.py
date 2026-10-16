"""崗位匹配端點（FR-1f）。採集流水線（P3）也復用 score_posting。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db import get_db
from app.services.matching import score_posting

router = APIRouter(prefix="/matches", tags=["matches"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]


@router.post("/{posting_id}/score", status_code=201)
def score(user: CurrentUser, db: DB, posting_id: str) -> dict:
    try:
        return score_posting(db, user["id"], posting_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("")
def list_matches(
    user: CurrentUser, db: DB, status: str | None = None,
    limit: int = 20, offset: int = 0,
) -> dict:
    limit = min(max(limit, 1), 100)
    rows = db.execute(
        text(
            """
            SELECT m.id, m.posting_id, m.match_score, m.hard_failures, m.reasons, m.status,
                   p.company_name, p.title, p.location, p.apply_url, p.first_seen_at
            FROM job_matches m
            JOIN job_postings p ON p.id = m.posting_id
            WHERE m.user_id = :uid AND (CAST(:st AS text) IS NULL OR CAST(m.status AS text) = :st)
            ORDER BY m.match_score DESC NULLS LAST, p.first_seen_at DESC
            LIMIT :lim OFFSET :off
            """
        ),
        {"uid": user["id"], "st": status, "lim": limit, "off": offset},
    ).mappings().all()
    total = db.execute(
        text(
            """
            SELECT COUNT(*) AS n FROM job_matches m
            WHERE m.user_id = :uid AND (CAST(:st AS text) IS NULL OR CAST(m.status AS text) = :st)
            """
        ),
        {"uid": user["id"], "st": status},
    ).mappings().one()["n"]
    return {
        "items": [
            {
                "id": str(r["id"]),
                "posting_id": str(r["posting_id"]),
                "match_score": r["match_score"],
                "hard_failures": r["hard_failures"] or [],
                "reasons": r["reasons"] or [],
                "status": r["status"],
                "company_name": r["company_name"],
                "title": r["title"],
                "location": r["location"],
                "apply_url": r["apply_url"],
                "first_seen_at": r["first_seen_at"].isoformat(),
            }
            for r in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }