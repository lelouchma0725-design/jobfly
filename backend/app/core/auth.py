"""Supabase Auth 集成：驗證前端傳來的 JWT 並注入當前用戶。

- 用戶登錄/註冊走 Supabase Auth（前端 supabase-js）
- 後端驗證 Bearer token 簽名（JWKS），確認對應 auth.users 存在
- 所有需要用戶身份的端點依賴 get_current_user
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Annotated

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)


@lru_cache(maxsize=1)
def _jwks() -> dict:
    url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
    try:
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:  # pragma: no cover
        logger.error("無法獲取 Supabase JWKS: %s", exc)
        raise RuntimeError("Supabase JWKS 不可用") from exc


def _decode_token(token: str) -> dict:
    try:
        unverified = jwt.get_unverified_header(token)
        kid = unverified["kid"]
        key = next(k for k in _jwks()["keys"] if k["kid"] == kid)
        return jwt.decode(
            token,
            key=jwt.algorithms.RSAAlgorithm.from_jwk(key),
            algorithms=["RS256"],
            audience="authenticated",
            options={"verify_aud": True},
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登錄已失效，請重新登錄") from exc


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """返回 {'id': uuid, 'email': str|None, 'phone': str|None, 'role': str}。

    同時保證 profiles 行存在（首次登錄自動補建）。
    """
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少登錄憑證")
    payload = _decode_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token 無效")

    row = db.execute(
        text(
            """
            INSERT INTO profiles (id, email, phone)
            VALUES (:id, :email, :phone)
            ON CONFLICT (id) DO UPDATE
              SET email = COALESCE(profiles.email, EXCLUDED.email),
                  phone = COALESCE(profiles.phone, EXCLUDED.phone)
            RETURNING id::text, email, phone, role
            """
        ),
        {
            "id": user_id,
            "email": payload.get("email"),
            "phone": payload.get("phone"),
        },
    ).mappings().one()
    db.commit()
    result = dict(row)
    # 管理員自動提升：ADMIN_EMAILS 中的郵箱登錄即成為 admin
    email = (result.get("email") or "").lower()
    if email and email in settings.admin_email_list and result.get("role") != "admin":
        db.execute(text("UPDATE profiles SET role='admin' WHERE id=:id"), {"id": user_id})
        db.commit()
        result["role"] = "admin"
    return result
