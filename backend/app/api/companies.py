"""關注公司管理 + 公司招聘官網自動發現。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
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
            """
            SELECT DISTINCT ON (COALESCE(careers_url, company_name)) id, company_name, aliases,
                   careers_url, platform, notes, is_active, created_at
            FROM watched_companies WHERE user_id = :uid
            ORDER BY COALESCE(careers_url, company_name), created_at
            """
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


class DiscoverRequest(BaseModel):
    name: str


@router.post("/discover")
def discover_company(user: CurrentUser, payload: DiscoverRequest) -> dict:
    """按公司名自動發現招聘官網：LLM 給候選 + 實網探測驗證。"""
    import re

    import httpx as _httpx

    from app.core.llm import chat_json

    name = payload.name.strip()[:100]
    out = chat_json(
        "你熟悉各公司招聘官網。給出公司招聘官網地址候選。輸出 JSON："
        '{"candidates": ["url1", "url2", ...], "careers_hint": "一句話說明"}',
        f"公司名：{name}",
        max_tokens=500,
    )
    verified = []
    for url in (out.get("candidates") or [])[:6]:
        if not url.startswith("http"):
            continue
        try:
            r = _httpx.get(url, timeout=12, follow_redirects=True,
                           headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                m = re.search(r"<title>([^<]*)</title>", r.text, re.I)
                verified.append({"url": str(r.url), "status": 200,
                                 "title": (m.group(1).strip()[:80] if m else None)})
            else:
                verified.append({"url": url, "status": r.status_code, "title": None})
        except Exception as exc:  # noqa: BLE001
            verified.append({"url": url, "status": "unreachable", "title": str(exc)[:80]})
    return {"name": name, "hint": out.get("careers_hint"), "candidates": verified}
