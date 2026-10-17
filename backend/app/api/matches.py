"""崗位匹配端點（FR-1f）。採集流水線（P3）也復用 score_posting。"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.jsonutil import loads_json
from app.db import get_db
from app.services.matching import score_posting

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/matches", tags=["matches"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]

REMATCH_LIMIT = 200  # 每輪評分上限（控制 LLM 成本）


def rematch_all_for_user(db: Session, user_id: str, limit: int = 30) -> dict:
    """用當前畫像對用戶匹配做一輪評分（補缺失優先 + 重算最舊的），返回進度。

    準確性 100% 策略：分批多輪直到 remaining=0；
    每輪優先補評「完全沒有 match 行」的崗位，再重算最舊的已有 match。
    """
    total = 0
    # 1) 補評缺失 match 的崗位（採集時漏評/新公司）
    missing = db.execute(
        text(
            """
            SELECT p.id FROM job_postings p
            LEFT JOIN job_matches m ON m.posting_id = p.id AND m.user_id = :u
            WHERE m.id IS NULL AND p.is_active = true
            ORDER BY p.first_seen_at DESC LIMIT :n
            """
        ),
        {"u": user_id, "n": limit},
    ).mappings().all()
    for r in missing:
        try:
            score_posting(db, user_id, str(r["id"]))
            total += 1
        except Exception:  # noqa: BLE001
            logger.exception("補評失敗 user=%s posting=%s", user_id, r["id"])
    # 2) 重算最舊的已有 match
    if len(missing) < limit:
        stale = db.execute(
            text(
                "SELECT posting_id FROM job_matches WHERE user_id=:u "
                "ORDER BY updated_at ASC LIMIT :n"
            ),
            {"u": user_id, "n": limit - len(missing)},
        ).mappings().all()
        for r in stale:
            try:
                score_posting(db, user_id, str(r["posting_id"]))
                total += 1
            except Exception:  # noqa: BLE001
                logger.exception("重新匹配失敗 user=%s posting=%s", user_id, r["posting_id"])
    # 3) 剩餘量（供進度查詢/多輪調度）
    remaining = db.execute(
        text(
            """
            SELECT (SELECT COUNT(*) FROM job_postings p
                    LEFT JOIN job_matches m ON m.posting_id = p.id AND m.user_id = :u
                    WHERE m.id IS NULL AND p.is_active = true) AS miss,
                   (SELECT COUNT(*) FROM job_matches WHERE user_id = :u) AS has
            """
        ),
        {"u": user_id},
    ).mappings().one()
    return {"scored": total, "remaining_missing": int(remaining["miss"]),
            "total_matches": int(remaining["has"])}


@router.post("/{posting_id}/score", status_code=201)
def score(user: CurrentUser, db: DB, posting_id: str) -> dict:
    try:
        return score_posting(db, user["id"], posting_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/companies")
def list_companies(user: CurrentUser, db: DB) -> list[dict]:
    """匹配頁公司篩選列表（公司 + 匹配數 + 最高分；含 hard_failed 的公司）。"""
    rows = db.execute(
        text(
            """
            SELECT p.company_name, COUNT(*) AS n, MAX(m.match_score) AS top
            FROM job_matches m JOIN job_postings p ON p.id = m.posting_id
            WHERE m.user_id = :uid
            GROUP BY p.company_name ORDER BY top DESC NULLS LAST, n DESC LIMIT 100
            """
        ),
        {"uid": user["id"]},
    ).mappings().all()
    return [
        {"company_name": r["company_name"], "count": r["n"], "top_score": r["top"]}
        for r in rows
    ]


def rematch_company(db: Session, user_id: str, company: str, batch: int = 50) -> dict:
    """按公司重新匹配：分批循環直到該公司全部崗位重算。"""
    total = 0
    for _ in range(20):  # 每輪 50 個，最多 1000 個/公司
        rows = db.execute(
            text(
                """
                SELECT p.id FROM job_postings p
                WHERE p.is_active = true AND p.company_name ILIKE '%'||:co||'%'
                ORDER BY p.first_seen_at DESC LIMIT :n OFFSET :off
                """
            ),
            {"co": company, "n": batch, "off": total},
        ).mappings().all()
        if not rows:
            break
        for r in rows:
            try:
                score_posting(db, user_id, str(r["id"]))
                total += 1
            except Exception:  # noqa: BLE001
                logger.exception("按公司匹配失敗 user=%s posting=%s", user_id, r["id"])
    return {"scored": total, "company": company, "remaining_missing": 0, "total_matches": total}


def rematch_full(db: Session, user_id: str, max_rounds: int = 30, batch: int = 30) -> dict:
    """分批多輪直到全量補評完成。返回最終進度。"""
    res = {"scored": 0, "remaining_missing": -1, "total_matches": 0}
    for _round in range(max_rounds):
        res = rematch_all_for_user(db, user_id, limit=batch)
        if res["remaining_missing"] == 0:
            break
    return res


class RematchRequest(BaseModel):
    company: str | None = None


@router.post("/rematch", status_code=202)
def rematch(user: CurrentUser, db: DB, payload: RematchRequest, background_tasks: BackgroundTasks) -> dict:
    """重新匹配：全量或按公司（補評缺失 + 重算），後台執行。"""
    uid = user["id"]
    company = (payload.company or "").strip()

    def _run() -> None:
        from app.db import SessionLocal

        s = SessionLocal()
        try:
            if company:
                res = rematch_company(s, uid, company)
            else:
                res = rematch_full(s, uid)
            logger.info("重新匹配完成 user=%s %s", uid, res)
        except Exception:  # noqa: BLE001
            logger.exception("重新匹配失敗 user=%s", uid)
        finally:
            s.close()

    background_tasks.add_task(_run)
    return {"started": True, "note": ("僅重新匹配該公司" if company else "全量重新匹配") + "，後台執行中"}


@router.get("/rematch-status")
def rematch_status(user: CurrentUser, db: DB) -> dict:
    """重新匹配進度：未評分崗位數 + 已有匹配數。"""
    row = db.execute(
        text(
            """
            SELECT (SELECT COUNT(*) FROM job_postings p
                    LEFT JOIN job_matches m ON m.posting_id = p.id AND m.user_id = :u
                    WHERE m.id IS NULL AND p.is_active = true) AS miss,
                   (SELECT COUNT(*) FROM job_matches WHERE user_id = :u) AS has
            """
        ),
        {"u": user["id"]},
    ).mappings().one()
    return {"remaining_missing": int(row["miss"]), "total_matches": int(row["has"])}


@router.get("")
def list_matches(
    user: CurrentUser, db: DB, status: str | None = None,
    company: str | None = None,
    limit: int = 20, offset: int = 0,
    campus: str | None = None, org: str | None = None,
) -> dict:
    limit = min(max(limit, 1), 100)
    rows = db.execute(
        text(
            """
            SELECT m.id, m.posting_id, m.match_score, m.priority_score, m.hard_failures,
                   m.reasons, m.score_breakdown, m.status,
                   p.company_name, p.title, p.location, p.department, p.is_campus,
                   p.org_level, p.apply_url, p.first_seen_at, p.raw->'directions' AS directions
            FROM job_matches m
            JOIN job_postings p ON p.id = m.posting_id
            WHERE m.user_id = :uid AND (CAST(:st AS text) IS NULL OR CAST(m.status AS text) = :st)
              AND (CAST(:co AS text) IS NULL OR p.company_name ILIKE '%'||:co||'%')
              AND (CAST(:ca AS text) IS NULL OR (CAST(:ca AS text)='campus' AND p.is_campus)
                   OR (CAST(:ca AS text)='society' AND NOT p.is_campus))
              AND (CAST(:og AS text) IS NULL OR p.org_level = :og)
            ORDER BY m.priority_score DESC NULLS LAST, m.match_score DESC NULLS LAST,
                     p.first_seen_at DESC
            LIMIT :lim OFFSET :off
            """
        ),
        {"uid": user["id"], "st": status, "co": company, "ca": campus, "og": org,
         "lim": limit, "off": offset},
    ).mappings().all()
    total = db.execute(
        text(
            """
            SELECT COUNT(*) AS n FROM job_matches m
            JOIN job_postings p ON p.id = m.posting_id
            WHERE m.user_id = :uid AND (CAST(:st AS text) IS NULL OR CAST(m.status AS text) = :st)
              AND (CAST(:co AS text) IS NULL OR p.company_name ILIKE '%'||:co||'%')
              AND (CAST(:ca AS text) IS NULL OR (CAST(:ca AS text)='campus' AND p.is_campus)
                   OR (CAST(:ca AS text)='society' AND NOT p.is_campus))
              AND (CAST(:og AS text) IS NULL OR p.org_level = :og)
            """
        ),
        {"uid": user["id"], "st": status, "co": company, "ca": campus, "og": org},
    ).mappings().one()["n"]
    return {
        "items": [
            {
                "id": str(r["id"]),
                "posting_id": str(r["posting_id"]),
                "match_score": r["match_score"],
                "priority_score": r["priority_score"],
                "is_campus": r["is_campus"],
                "org_level": r["org_level"],
                "department": r["department"],
                "directions": loads_json(r["directions"])
                if isinstance(r["directions"], str) else (r["directions"] or []),
                "hard_failures": r["hard_failures"] or [],
                "score_breakdown": r["score_breakdown"] or {},
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
