"""關注公司管理（FR-1d 後半：讓用戶確定希望投遞/關注的公司）。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.auth import get_current_user
from app.core.jsonutil import j
from app.db import get_db
from app.schemas.accounts import PLATFORMS, WatchedCompanyCreate, WatchedCompanyUpdate

router = APIRouter(prefix="/companies", tags=["companies"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]


@router.get("")
def list_companies(user: CurrentUser, db: DB) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT id, company_name, aliases, careers_url, platform, notes, is_active, created_at "
            "FROM watched_companies WHERE user_id = :uid ORDER BY created_at DESC"
        ),
        {"uid": user["id"]},
    ).mappings().all()
    return [
        {
            "id": str(r["id"]),
            "company_name": r["company_name"],
            "aliases": r["aliases"] or [],
            "careers_url": r["careers_url"],
            "platform": r["platform"],
            "notes": r["notes"],
            "is_active": r["is_active"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


@router.post("", status_code=201)
def create_company(
    user: CurrentUser, db: DB, payload: WatchedCompanyCreate, request: Request
) -> dict:
    if payload.platform not in PLATFORMS:
        raise HTTPException(422, f"platform 必須是 {PLATFORMS} 之一")
    row = db.execute(
        text(
            """
            INSERT INTO watched_companies
              (user_id, company_name, aliases, careers_url, platform, notes)
            VALUES (:uid, :name, CAST(:aliases AS jsonb), :url, :platform, :notes)
            RETURNING id
            """
        ),
        {
            "uid": user["id"],
            "name": payload.company_name,
            "aliases": j(payload.aliases or []),
            "url": payload.careers_url,
            "platform": payload.platform,
            "notes": payload.notes,
        },
    ).mappings().one()
    db.commit()
    log_audit(db, user["id"], "company.create", "watched_companies", str(row["id"]),
              {"name": payload.company_name}, request.client.host if request.client else None)
    return {"id": str(row["id"])}


@router.patch("/{company_id}")
def update_company(
    user: CurrentUser, db: DB, company_id: str, payload: WatchedCompanyUpdate
) -> dict:
    fields = payload.model_dump(exclude_none=True)
    if "aliases" in fields:
        fields["aliases"] = j(fields["aliases"] or [])
    sets = ", ".join(f"{k} = CAST(:{k} AS jsonb)" if k == "aliases" else f"{k} = :{k}"
                     for k in fields)
    result = db.execute(
        text(
            f"UPDATE watched_companies SET {sets}, updated_at = now() "
            "WHERE id = :cid AND user_id = :uid RETURNING id"
        ) if sets else text("SELECT id FROM watched_companies WHERE id = :cid AND user_id = :uid"),
        {"cid": company_id, "uid": user["id"], **fields},
    )
    db.commit()
    if not result.first():
        raise HTTPException(404, "公司不存在")
    return {"ok": True}


@router.delete("/{company_id}", status_code=204)
def delete_company(user: CurrentUser, db: DB, company_id: str) -> None:
    row = db.execute(
        text("DELETE FROM watched_companies WHERE id = :cid AND user_id = :uid RETURNING id"),
        {"cid": company_id, "uid": user["id"]},
    ).first()
    if not row:
        raise HTTPException(404, "公司不存在")
    db.commit()
