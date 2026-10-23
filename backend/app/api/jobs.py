"""崗位瀏覽與手動採集端點（FR-3a）。"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.textutil import t2s
from app.core.jsonutil import j
from app.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]


class CollectRequest(BaseModel):
    company: str | None = None


@router.get("")
def list_jobs(
    user: CurrentUser, db: DB, q: str | None = None, company: str | None = None,
    campus: str | None = None, org: str | None = None,
    job_type: str | None = None,
    limit: int = 20, offset: int = 0,
) -> dict:
    q = t2s(q) or None
    company = t2s(company) or None
    limit = min(max(limit, 1), 200)
    rows = db.execute(
        text(
            """
            SELECT p.id, p.company_name, p.title, p.location, p.department, p.source,
                   p.apply_url, p.first_seen_at, p.posted_at, p.is_campus, p.is_intern, p.org_level,
                   m.match_score, m.priority_score, m.status AS match_status, m.id AS match_id
            FROM job_postings p
            LEFT JOIN job_matches m ON m.posting_id = p.id AND m.user_id = :uid
            WHERE p.is_active = true
              AND (CAST(:q AS text) IS NULL OR p.title ILIKE '%'||:q||'%' OR p.description_text ILIKE '%'||:q||'%')
              AND (CAST(:co AS text) IS NULL OR p.company_name ILIKE '%'||:co||'%')
              AND (CAST(:jt AS text) IS NULL OR
                   (CAST(:jt AS text)='campus' AND p.is_campus AND NOT p.is_intern)
                   OR (CAST(:jt AS text)='society' AND NOT p.is_campus AND NOT p.is_intern)
                   OR (CAST(:jt AS text)='intern' AND p.is_intern))
              AND (CAST(:ca AS text) IS NULL OR (CAST(:ca AS text)='campus' AND p.is_campus)
                   OR (CAST(:ca AS text)='society' AND NOT p.is_campus))
              AND (CAST(:og AS text) IS NULL OR p.org_level = :og)
            ORDER BY p.first_seen_at DESC
            LIMIT :lim OFFSET :off
            """
        ),
        {"uid": user["id"], "q": q, "co": company, "ca": campus, "og": org,
         "jt": job_type, "lim": limit, "off": offset},
    ).mappings().all()
    total = db.execute(
        text(
            """
            SELECT COUNT(*) AS n FROM job_postings p
            WHERE p.is_active = true
              AND (CAST(:q AS text) IS NULL OR p.title ILIKE '%'||:q||'%' OR p.description_text ILIKE '%'||:q||'%')
              AND (CAST(:co AS text) IS NULL OR p.company_name ILIKE '%'||:co||'%')
              AND (CAST(:jt AS text) IS NULL OR
                   (CAST(:jt AS text)='campus' AND p.is_campus AND NOT p.is_intern)
                   OR (CAST(:jt AS text)='society' AND NOT p.is_campus AND NOT p.is_intern)
                   OR (CAST(:jt AS text)='intern' AND p.is_intern))
              AND (CAST(:ca AS text) IS NULL OR (CAST(:ca AS text)='campus' AND p.is_campus)
                   OR (CAST(:ca AS text)='society' AND NOT p.is_campus))
              AND (CAST(:og AS text) IS NULL OR p.org_level = :og)
            """
        ),
        {"q": q, "co": company, "ca": campus, "og": org, "jt": job_type},
    ).mappings().one()["n"]
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
                "priority_score": r["priority_score"],
                "is_campus": r["is_campus"],
                "is_intern": r["is_intern"],
                "org_level": r["org_level"],
                "match_status": r["match_status"],
                "match_id": str(r["match_id"]) if r["match_id"] else None,
            }
            for r in rows
        ],
        "limit": limit,
        "offset": offset,
        "total": total,
    }


@router.get("/collect-status")
def collect_status(user: CurrentUser, db: DB) -> dict:
    """採集進度：前台輪詢此端點，running=false 且 finished_at 有值即完成。"""
    row = db.execute(
        text("SELECT collect_state FROM user_settings WHERE user_id=:u"),
        {"u": user["id"]},
    ).mappings().first()
    return dict(row["collect_state"] or {}) if row and row["collect_state"] else {"running": False}


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
def run_collect(user: CurrentUser, db: DB, payload: CollectRequest, background_tasks: BackgroundTasks) -> dict:
    """異步觸發：全量或按公司採集 + 匹配（後台執行）。"""
    from app.collectors.pipeline import collect_for_user

    uid = user["id"]
    company = (payload.company or "").strip()

    def _run() -> None:
        import datetime as _dt

        from app.db import SessionLocal

        s = SessionLocal()
        s.execute(
            text(
                "INSERT INTO user_settings (user_id, collect_state) VALUES (:u, CAST(:st AS jsonb)) "
                "ON CONFLICT (user_id) DO UPDATE SET collect_state=CAST(:st AS jsonb), updated_at=now()"
            ),
            {"u": uid, "st": j({"running": True, "finished_at": None, "report": None})},
        )
        s.commit()
        try:
            report = collect_for_user(s, uid, company_name=company or None)
            s.execute(
                text(
                    "UPDATE user_settings SET collect_state=CAST(:st AS jsonb), updated_at=now() "
                    "WHERE user_id=:u"
                ),
                {"u": uid, "st": j({
                    "running": False,
                    "finished_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                    "report": {k: report.get(k) for k in ("new", "updated", "matched", "errors", "collected")},
                })},
            )
            s.commit()
        except Exception:  # noqa: BLE001
            logger.exception("後台採集失敗 user=%s", uid)
            s.execute(
                text(
                    "UPDATE user_settings SET collect_state=CAST(:st AS jsonb), updated_at=now() "
                    "WHERE user_id=:u"
                ),
                {"u": uid, "st": j({"running": False, "finished_at": None, "report": {"errors": 1}})},
            )
            s.commit()
        finally:
            s.close()

    background_tasks.add_task(_run)
    return {"started": True, "note": ("僅採集該公司" if company else "全量採集") + "，後台執行中"}


@router.get("/collect-status")
def collect_status(user: CurrentUser, db: DB) -> dict:
    """採集進度：前台輪詢此端點，running=false 且 finished_at 有值即完成。"""
    row = db.execute(
        text("SELECT collect_state FROM user_settings WHERE user_id=:u"),
        {"u": user["id"]},
    ).mappings().first()
    return dict(row["collect_state"] or {}) if row and row["collect_state"] else {"running": False}
