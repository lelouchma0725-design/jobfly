"""平台帳號加密庫（FR-1d / 主程序同步 GAP-2）。

- 寫入：為用戶生成/取回 DEK → 信封加密 → 落庫（密文）
- 讀取：僅返回掩碼後的帳號標識，永不下發密文/明文
- 解密密文只發生在採集/投遞 Worker（P3/P4），通過 get_dek_for_user 取用
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.auth import get_current_user
from app.core.security import (
    decrypt_field,
    encrypt_field,
    encrypt_json,
    get_dek_for_user,
)
from app.db import get_db
from app.schemas.accounts import PLATFORMS, AccountCreate, AccountUpdate

router = APIRouter(prefix="/accounts", tags=["accounts"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]


def _mask(identifier: str) -> str:
    if len(identifier) <= 4:
        return "****"
    return identifier[:2] + "****" + identifier[-2:]


@router.get("")
def list_accounts(user: CurrentUser, db: DB) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT id, platform, label, login_identifier_enc, status, last_login_at, last_error "
            "FROM platform_accounts WHERE user_id = :uid ORDER BY created_at"
        ),
        {"uid": user["id"]},
    ).mappings().all()
    dek = get_dek_for_user(db, user["id"])
    result = []
    for r in rows:
        result.append(
            {
                "id": str(r["id"]),
                "platform": r["platform"],
                "label": r["label"],
                "login_masked": _mask(decrypt_field(dek, r["login_identifier_enc"])),
                "status": r["status"],
                "last_login_at": r["last_login_at"].isoformat() if r["last_login_at"] else None,
                "last_error": r["last_error"],
            }
        )
    return result


@router.post("", status_code=201)
def create_account(user: CurrentUser, db: DB, payload: AccountCreate, request: Request) -> dict:
    if payload.platform not in PLATFORMS:
        raise HTTPException(422, f"platform 必須是 {PLATFORMS} 之一")
    dek = get_dek_for_user(db, user["id"])
    row_id = db.execute(
        text(
            """
            INSERT INTO platform_accounts
              (user_id, platform, label, login_identifier_enc, password_enc, meta_enc)
            VALUES (:uid, :platform, :label, :ident, :pwd, :meta)
            RETURNING id
            """
        ),
        {
            "uid": user["id"],
            "platform": payload.platform,
            "label": payload.label,
            "ident": encrypt_field(dek, payload.login_identifier),
            "pwd": encrypt_field(dek, payload.password),
            "meta": encrypt_json(dek, payload.meta) if payload.meta is not None else None,
        },
    ).mappings().one()
    db.commit()
    log_audit(db, user["id"], "account.create", "platform_accounts", str(row_id["id"]),
              {"platform": payload.platform}, request.client.host if request.client else None)
    return {"id": str(row_id["id"])}


@router.patch("/{account_id}")
def update_account(
    user: CurrentUser, db: DB, account_id: str, payload: AccountUpdate, request: Request
) -> dict:
    exists = db.execute(
        text("SELECT 1 FROM platform_accounts WHERE id = :aid AND user_id = :uid"),
        {"aid": account_id, "uid": user["id"]},
    ).first()
    if not exists:
        raise HTTPException(404, "帳號不存在")
    dek = get_dek_for_user(db, user["id"])
    fields = payload.model_dump(exclude_none=True)
    sets, params = [], {"aid": account_id, "uid": user["id"]}
    if "label" in fields:
        sets.append("label = :label")
        params["label"] = fields["label"]
    if "login_identifier" in fields:
        sets.append("login_identifier_enc = :ident")
        params["ident"] = encrypt_field(dek, fields["login_identifier"])
    if "password" in fields:
        sets.append("password_enc = :pwd")
        params["pwd"] = encrypt_field(dek, fields["password"])
    if "meta" in fields:
        sets.append("meta_enc = :meta")
        params["meta"] = encrypt_json(dek, fields["meta"]) if fields["meta"] is not None else None
    if sets:
        sets.append("status = 'pending_verify'")  # 憑據變更後需重新驗證登錄態
        db.execute(
            text(
                f"UPDATE platform_accounts SET {', '.join(sets)}, updated_at = now() "
                "WHERE id = :aid AND user_id = :uid"
            ),
            params,
        )
        db.commit()
        log_audit(db, user["id"], "account.update", "platform_accounts", account_id,
                  {}, request.client.host if request.client else None)
    return {"ok": True}


@router.delete("/{account_id}", status_code=204)
def delete_account(user: CurrentUser, db: DB, account_id: str, request: Request) -> None:
    row = db.execute(
        text("DELETE FROM platform_accounts WHERE id = :aid AND user_id = :uid RETURNING id"),
        {"aid": account_id, "uid": user["id"]},
    ).first()
    if not row:
        raise HTTPException(404, "帳號不存在")
    db.commit()
    log_audit(db, user["id"], "account.delete", "platform_accounts", account_id,
              {}, request.client.host if request.client else None)
