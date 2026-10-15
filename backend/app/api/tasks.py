"""人工接管任務端點（FR-3c：直接框 → 回填 → 繼續投遞）。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db import get_db
from app.services.apply_engine import answer_and_resume

router = APIRouter(prefix="/manual-tasks", tags=["manual-tasks"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]


class TaskAnswer(BaseModel):
    answer: dict | None = None


@router.get("")
def list_tasks(user: CurrentUser, db: DB, status: str = "open") -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT t.id, t.task_type, t.question, t.options, t.status, t.created_at,
                   t.expires_at, a.status AS app_status,
                   p.company_name, p.title
            FROM manual_tasks t
            JOIN applications a ON a.id = t.application_id
            JOIN job_postings p ON p.id = a.posting_id
            WHERE t.user_id = :uid AND t.status = :st
            ORDER BY t.created_at DESC LIMIT 100
            """
        ),
        {"uid": user["id"], "st": status},
    ).mappings().all()
    return [
        {
            "id": str(r["id"]),
            "task_type": r["task_type"],
            "question": r["question"],
            "options": r["options"] or {},
            "status": r["status"],
            "created_at": r["created_at"].isoformat(),
            "expires_at": r["expires_at"].isoformat(),
            "application_status": r["app_status"],
            "company_name": r["company_name"],
            "title": r["title"],
        }
        for r in rows
    ]


@router.post("/{task_id}/answer", status_code=200)
def answer_task(user: CurrentUser, db: DB, task_id: str, payload: TaskAnswer) -> dict:
    result = answer_and_resume(db, task_id, user["id"], payload.answer)
    if result.get("error"):
        raise HTTPException(404, result["error"])
    return result


@router.post("/{task_id}/cancel", status_code=200)
def cancel_task(user: CurrentUser, db: DB, task_id: str) -> dict:
    row = db.execute(
        text(
            "UPDATE manual_tasks SET status='cancelled' "
            "WHERE id=:id AND user_id=:uid AND status='open' RETURNING application_id"
        ),
        {"id": task_id, "uid": user["id"]},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "任務不存在或已處理")
    db.execute(
        text(
            "UPDATE applications SET status='aborted', status_reason='人工任務已取消', updated_at=now() "
            "WHERE id=:aid"
        ),
        {"aid": row["application_id"]},
    )
    db.commit()
    return {"ok": True}
