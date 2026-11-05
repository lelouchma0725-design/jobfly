"""管理後台端點（GAP-10）：用戶審計、適配器健康、投遞成功率、LLM 用量、審計日誌。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.llm import usage as llm_usage
from app.db import get_db

router = APIRouter(prefix="/admin", tags=["admin"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]


def require_admin(user: CurrentUser) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(403, "需要管理員權限")
    return user


Admin = Annotated[dict, Depends(require_admin)]


@router.get("/stats")
def stats(admin: Admin, db: DB) -> dict:
    one = lambda sql, **kw: db.execute(text(sql), kw).mappings().one()  # noqa: E731
    users = one("SELECT COUNT(*) AS n FROM profiles WHERE deleted_at IS NULL")["n"]
    active_postings = one("SELECT COUNT(*) AS n FROM job_postings WHERE is_active=true")["n"]
    matches_24h = one(
        "SELECT COUNT(*) AS n FROM job_matches WHERE created_at >= now() - interval '24 hours'"
    )["n"]
    apps = one(
        """
        SELECT COUNT(*) FILTER (WHERE submitted_at >= now() - interval '24 hours') AS submitted_24h,
               COUNT(*) AS total FROM applications
        """
    )
    open_tasks = one("SELECT COUNT(*) AS n FROM manual_tasks WHERE status='open'")["n"]
    accounts_issues = one(
        "SELECT COUNT(*) AS n FROM platform_accounts WHERE status IN ('expired','error','locked')"
    )["n"]
    return {
        "users": users,
        "active_postings": active_postings,
        "matches_24h": matches_24h,
        "applications_total": apps["total"],
        "applications_submitted_24h": apps["submitted_24h"],
        "open_manual_tasks": open_tasks,
        "platform_accounts_issue": accounts_issues,
        "llm_usage": llm_usage(),
        "collected_today": one(
            "SELECT COUNT(*) AS n FROM job_postings WHERE first_seen_at::date = now()::date"
        )["n"],
    }


@router.get("/users")
def list_users(admin: Admin, db: DB) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT p.id, p.email, p.phone, p.role, p.created_at, p.deleted_at,
                   (SELECT COUNT(*) FROM applications a WHERE a.user_id=p.id) AS apps,
                   (SELECT COUNT(*) FROM job_matches m WHERE m.user_id=p.id) AS matches
            FROM profiles p ORDER BY p.created_at DESC LIMIT 500
            """
        )
    ).mappings().all()
    return [
        {
            "id": str(r["id"]), "email": r["email"], "phone": r["phone"], "role": r["role"],
            "created_at": r["created_at"].isoformat(),
            "disabled": r["deleted_at"] is not None,
            "applications": r["apps"], "matches": r["matches"],
        }
        for r in rows
    ]


@router.patch("/users/{user_id}")
def set_user(admin: Admin, db: DB, user_id: str, disabled: bool | None = None,
             role: str | None = None) -> dict:
    sets, params = [], {"id": user_id}
    if disabled is not None:
        sets.append("deleted_at = " + ("now()" if disabled else "NULL"))
    if role in ("user", "admin"):
        sets.append("role = :role")
        params["role"] = role
    if not sets:
        raise HTTPException(422, "無有效變更")
    row = db.execute(
        text(f"UPDATE profiles SET {', '.join(sets)} WHERE id=:id RETURNING id"),
        params,
    ).first()
    if not row:
        raise HTTPException(404, "用戶不存在")
    db.commit()
    return {"ok": True}


@router.get("/adapters")
def adapters(admin: Admin, db: DB) -> list[dict]:
    rows = db.execute(
        text("SELECT * FROM adapter_health ORDER BY adapter")
    ).mappings().all()
    return [
        {
            "adapter": r["adapter"], "last_run_at": r["last_run_at"].isoformat() if r["last_run_at"] else None,
            "last_success_at": r["last_success_at"].isoformat() if r["last_success_at"] else None,
            "success_count": r["success_count"], "fail_count": r["fail_count"],
            "last_error": r["last_error"], "avg_duration_ms": r["avg_duration_ms"],
        }
        for r in rows
    ]


@router.get("/audit")
def audit(admin: Admin, db: DB, limit: int = 100) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT a.created_at, a.action, a.entity, a.entity_id, a.meta, p.email
            FROM audit_logs a LEFT JOIN profiles p ON p.id = a.actor_user_id
            ORDER BY a.created_at DESC LIMIT :lim
            """
        ),
        {"lim": min(limit, 500)},
    ).mappings().all()
    return [
        {
            "at": r["created_at"].isoformat(), "actor": r["email"], "action": r["action"],
            "entity": r["entity"], "entity_id": r["entity_id"], "meta": r["meta"],
        }
        for r in rows
    ]


@router.get("/collect-jobs")
def collect_jobs(admin: Admin, db: DB, limit: int = 50) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT kind, status, payload, scheduled_at, started_at, finished_at, error "
            "FROM collect_jobs ORDER BY created_at DESC LIMIT :lim"
        ),
        {"lim": min(limit, 200)},
    ).mappings().all()
    return [
        {
            "kind": r["kind"], "status": r["status"], "payload": r["payload"],
            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
            "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
            "error": r["error"],
        }
        for r in rows
    ]
