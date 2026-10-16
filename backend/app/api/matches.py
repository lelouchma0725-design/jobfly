"""崗位匹配端點（FR-1f）。採集流水線（P3）也復用 score_posting。"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db import get_db
from app.services.matching import score_posting

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/matches", tags=["matches"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]

REMATCH_LIMIT = 200  # 每輪重新匹配上限（控制 LLM 成本）


def rematch_all_for_user(db: Session, user_id: str, limit: int = REMATCH_LIMIT) -> int:
    """用當前畫像重新評分用戶的歷史匹配（保留 applied/applying 狀態）。"""
    rows = db.execute(
        text(
            "SELECT posting_id FROM job_matches WHERE user_id=:u "
            "ORDER BY updated_at DESC LIMIT :n"
        ),
        {"u": user_id, "n": limit},
    ).mappings().all()
    done = 0
    for r in rows:
        try:
            score_posting(db, user_id, str(r["posting_id"]))
            done += 1
        except Exception:  # noqa: BLE001
            logger.exception("重新匹配失敗 user=%s posting=%s", user_id, r["posting_id"])
    return done


@router.post("/{posting_id}/score", status_code=201)
def score(user: CurrentUser, db: DB, posting_id: str) -> dict:
    try:
        return score_posting(db, user["id"], posting_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/companies")
def list_companies(user: CurrentUser, db: DB) -> list[dict]:
    """匹配頁公司篩選列表（公司 + 匹配數 + 最高分）。"""
    rows = db.execute(
        text(
            """
            SELECT p.company_name, COUNT(*) AS n, MAX(m.match_score) AS top
            FROM job_matches m JOIN job_postings p ON p.id = m.posting_id
            WHERE m.user_id = :uid AND m.match_score IS NOT NULL
            GROUP BY p.company_name ORDER BY top DESC NULLS LAST, n DESC LIMIT 100
            """
        ),
        {"uid": user["id"]},
    ).mappings().all()
    return [
        {"company_name": r["company_name"], "count": r["n"], "top_score": r["top"]}
        for r in rows
    ]


@router.post("/rematch", status_code=202)
def rematch(user: CurrentUser, db: DB, background_tasks: BackgroundTasks) -> dict:
    """重新匹配：用當前畫像對全部歷史匹配重新評分（後台執行）。"""
    uid = user["id"]

    def _run() -> None:
        from app.db import SessionLocal

        s = SessionLocal()
        try:
            n = rematch_all_for_user(s, uid)
            logger.info("重新匹配完成 user=%s count=%s", uid, n)
        except Exception:  # noqa: BLE001
            logger.exception("重新匹配失敗 user=%s", uid)
        finally:
            s.close()

    background_tasks.add_task(_run)
    return {"started": True, "note": "重新匹配在後台執行（每輪最多 200 個），稍後刷新查看"}


@router.get("")
def list_matches(
    user: CurrentUser, db: DB, status: str | None = None,
    company: str | None = None,
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
              AND (CAST(:co AS text) IS NULL OR p.company_name ILIKE '%'||:co||'%')
            ORDER BY m.match_score DESC NULLS LAST, p.first_seen_at DESC
            LIMIT :lim OFFSET :off
            """
        ),
        {"uid": user["id"], "st": status, "co": company, "lim": limit, "off": offset},
    ).mappings().all()
    total = db.execute(
        text(
            """
            SELECT COUNT(*) AS n FROM job_matches m
            JOIN job_postings p ON p.id = m.posting_id
            WHERE m.user_id = :uid AND (CAST(:st AS text) IS NULL OR CAST(m.status AS text) = :st)
              AND (CAST(:co AS text) IS NULL OR p.company_name ILIKE '%'||:co||'%')
            """
        ),
        {"uid": user["id"], "st": status, "co": company},
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
