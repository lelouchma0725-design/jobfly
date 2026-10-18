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


@router.get("/{task_id}/fill-plan")
def task_fill_plan(user: CurrentUser, db: DB, task_id: str) -> dict:
    """RPA 輔助：為人工投遞生成「填寫方案」（按當前資料整理好的答案，可一鍵複製）。"""
    from app.services.apply_engine import _load_application
    from app.services.form_mapping import build_candidate_payload

    task = db.execute(
        text("SELECT application_id FROM manual_tasks WHERE id=:id AND user_id=:uid"),
        {"id": task_id, "uid": user["id"]},
    ).mappings().first()
    if not task:
        raise HTTPException(404, "任務不存在")
    app = _load_application(db, str(task["application_id"]))
    if not app:
        raise HTTPException(404, "投遞不存在")
    payload = build_candidate_payload(db, user["id"])
    skills = ", ".join(s["name"] for s in (payload.get("skills") or []))
    exp_lines = []
    for e in (payload.get("experiences") or [])[:5]:
        exp_lines.append(
            f"{e.get('start')} ~ {e.get('end')} {e.get('company')} {e.get('title')}："
            + "；".join((e.get("bullets") or [])[:2])
        )
    edu_lines = [
        f"{e.get('school')} {e.get('degree')} {e.get('major')}"
        for e in (payload.get("education") or [])
    ]
    fields = {
        "姓名": payload.get("full_name") or "（未填）",
        "手機": payload.get("phone") or "（未填）",
        "郵箱": payload.get("email") or "（未填）",
        "簽證狀態": payload.get("visa_status") or "（未填）",
        "期望薪資": payload.get("salary_expectation") or "（未填）",
        "可到崗時間": payload.get("availability") or "（未填）",
        "技能（複製到技能欄）": skills,
        "工作經歷（最多 5 段，每段兩行內）": "\n".join(exp_lines) or "（未填）",
        "教育（複製到教育欄）": "；".join(edu_lines) or "（未填）",
    }
    text_block = "\n".join(f"{k}：{v}" for k, v in fields.items())
    # 機器可讀字段（RPA 擴展用）+ 簡歷文件（供 RPA 上傳）
    machine_fields = [
        {"key": "name", "label": "姓名", "value": payload.get("full_name") or ""},
        {"key": "phone", "label": "手機", "value": payload.get("phone") or ""},
        {"key": "email", "label": "郵箱", "value": payload.get("email") or ""},
        {"key": "visa", "label": "簽證", "value": payload.get("visa_status") or ""},
        {"key": "salary", "label": "薪資", "value": payload.get("salary_expectation") or ""},
        {"key": "availability", "label": "到崗", "value": payload.get("availability") or ""},
        {"key": "skills", "label": "技能", "value": skills},
        {"key": "experience", "label": "經歷", "value": "\n".join(exp_lines)},
        {"key": "education", "label": "教育", "value": "；".join(edu_lines)},
    ]
    resume = None
    rf = payload.get("resume_file")
    if rf:
        from app.config import settings
        from app.core.r2 import object_url, presigned_url

        url = object_url(rf.get("storage_path")) if settings.r2_public_base_url \
            else presigned_url(rf.get("storage_path"))
        resume = {"name": rf.get("name"), "storage_path": rf.get("storage_path"),
                  "download_url": url}
    return {"fields": fields, "copy_text": text_block, "machine_fields": machine_fields,
            "resume": resume, "company": app["company_name"], "title": app["title"],
            "apply_url": app.get("apply_url")}


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
