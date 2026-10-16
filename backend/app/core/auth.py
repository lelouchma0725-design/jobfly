"""用戶認證：驗證前端傳來的 Supabase JWT 並注入當前用戶。

- 前端登錄/註冊走後端認證代理（app/api/auth.py），瀏覽器不直連 supabase.co
- 後端驗證 token：優先調 Supabase /auth/v1/user（權威），失敗退 JWKS 本地驗簽
- 進程內緩存驗證結果（5 分鐘），降低每個請求的網絡往返
- 首次訪問自動補建 profiles 行；ADMIN_EMAILS 中的郵箱自動提升 admin
"""
from __future__ import annotations

import logging
import time
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

# token -> (expire_ts, user_id, email)
_verify_cache: dict[str, tuple[float, str, str | None]] = {}
_CACHE_TTL = 300


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


def _verify_via_api(token: str) -> tuple[str, str | None] | None:
    """調 Supabase /auth/v1/user 驗證，返回 (user_id, email) 或 None。"""
    try:
        resp = httpx.get(
            f"{settings.supabase_url}/auth/v1/user",
            headers={
                "apikey": settings.supabase_anon_key,
                "Authorization": f"Bearer {token}",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data["id"], data.get("email")
    except httpx.HTTPError:
        pass
    return None


def _verify_local(token: str) -> tuple[str, str | None] | None:
    try:
        unverified = jwt.get_unverified_header(token)
        kid = unverified["kid"]
        key = next(k for k in _jwks()["keys"] if k["kid"] == kid)
        payload = jwt.decode(
            token,
            key=jwt.algorithms.RSAAlgorithm.from_jwk(key),
            algorithms=["RS256"],
            audience="authenticated",
            options={"verify_aud": True},
        )
        return payload.get("sub"), payload.get("email")
    except Exception:  # noqa: BLE001
        return None


def verify_token(token: str) -> tuple[str, str | None]:
    """驗證 token，返回 (user_id, email)。兩種方式都失敗 → 401。"""
    now = time.time()
    hit = _verify_cache.get(token)
    if hit and hit[0] > now:
        return hit[1], hit[2]
    result = _verify_via_api(token) or _verify_local(token)
    if not result:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登錄已失效，請重新登錄")
    try:
        exp = jwt.decode(token, options={"verify_signature": False}).get("exp")
        ttl = min(_CACHE_TTL, max(0, int(exp) - int(now))) if exp else _CACHE_TTL
    except Exception:  # noqa: BLE001
        ttl = _CACHE_TTL
    _verify_cache[token] = (now + ttl, result[0], result[1])
    return result


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """返回 {'id': uuid, 'email': str|None, 'phone': str|None, 'role': str}。"""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少登錄憑證")
    user_id, email = verify_token(credentials.credentials)

    row = db.execute(
        text(
            """
            INSERT INTO profiles (id, email, phone)
            VALUES (:id, :email, :phone)
            ON CONFLICT (id) DO UPDATE
              SET email = COALESCE(profiles.email, EXCLUDED.email),
                  phone = COALESCE(profiles.phone, EXCLUDED.phone)
            RETURNING id::text, email, phone, role, full_name
            """
        ),
        {"id": user_id, "email": email, "phone": None},
    ).mappings().one()
    db.commit()
    result = dict(row)
    # 管理員自動提升：ADMIN_EMAILS 中的郵箱登錄即成為 admin
    email_lower = (result.get("email") or "").lower()
    if email_lower and email_lower in settings.admin_email_list and result.get("role") != "admin":
        db.execute(text("UPDATE profiles SET role='admin' WHERE id=:id"), {"id": user_id})
        db.commit()
        result["role"] = "admin"
    return result
