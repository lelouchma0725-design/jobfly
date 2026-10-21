"""認證代理（關鍵架構）：前端不直連 supabase.co，全部 auth 請求經後端轉發。

原因：部分地區網絡無法直達 *.supabase.co（實測本網絡連接被重置）。
後端部署於美區（Render），可正常訪問 Supabase Auth API。
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])

_SB = settings.supabase_url.rstrip("/")


def _anon_key() -> str:
    return settings.supabase_anon_key


def _anon_headers() -> dict:
    k = _anon_key()
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}


class Credentials(BaseModel):
    email: str
    password: str


class MagicLinkRequest(BaseModel):
    email: str


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/signup")
def signup(payload: Credentials) -> dict:
    try:
        resp = httpx.post(
            f"{_SB}/auth/v1/signup", headers=_anon_headers(),
            json={"email": payload.email, "password": payload.password}, timeout=20,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"無法連接 Supabase Auth（服務端網絡問題）: {exc}") from exc
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, _err(resp))
    data = resp.json()
    if not data.get("session"):
        return {"status": "email_confirmation_required", "user": data.get("user")}
    return {"status": "ok", "session": data["session"], "user": data["user"]}


@router.post("/signin")
def signin(payload: Credentials) -> dict:
    try:
        resp = httpx.post(
            f"{_SB}/auth/v1/token?grant_type=password", headers=_anon_headers(),
            json={"email": payload.email, "password": payload.password}, timeout=20,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"無法連接 Supabase Auth（服務端網絡問題）: {exc}") from exc
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, _err(resp))
    return resp.json()


@router.post("/magic-link")
def magic_link(payload: MagicLinkRequest) -> dict:
    try:
        resp = httpx.post(
            f"{_SB}/auth/v1/magiclink", headers=_anon_headers(),
            json={"email": payload.email, "emailRedirectTo": settings.frontend_url}, timeout=20,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"無法連接 Supabase Auth（服務端網絡問題）: {exc}") from exc
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, _err(resp))
    return {"status": "sent"}


@router.post("/refresh")
def refresh(payload: RefreshRequest) -> dict:
    try:
        resp = httpx.post(
            f"{_SB}/auth/v1/token?grant_type=refresh_token", headers=_anon_headers(),
            json={"refresh_token": payload.refresh_token}, timeout=20,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"無法連接 Supabase Auth（服務端網絡問題）: {exc}") from exc
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, _err(resp))
    return resp.json()


class AdminCreate(BaseModel):
    email: str
    password: str
    secret: str


@router.post("/admin-create")
def admin_create(payload: AdminCreate) -> dict:
    """維護端點：用 service_role 走 GoTrue 管理 API 正規創建用戶（含郵箱確認）。

    僅供管理員運維使用，secret 由 OPS_SECRET 環境變量保護。
    """
    if not settings.ops_secret or payload.secret != settings.ops_secret:
        raise HTTPException(403, "forbidden")
    try:
        resp = httpx.post(
            f"{_SB}/auth/v1/admin/users",
            headers={
                "apikey": settings.supabase_service_role_key,
                "Authorization": f"Bearer {settings.supabase_service_role_key}",
                "Content-Type": "application/json",
            },
            json={"email": payload.email, "password": payload.password, "email_confirm": True},
            timeout=25,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"無法連接 Supabase Auth: {exc}") from exc
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        body = resp.text[:300]
    return {"status": resp.status_code, "body": body}


def _err(resp: httpx.Response) -> str:
    try:
        return resp.json().get("msg") or resp.json().get("error_description") or resp.text[:300]
    except Exception:  # noqa: BLE001
        return resp.text[:300]

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.post("/change-password")
def change_password(user: CurrentUser, db: DB, payload: ChangePasswordRequest, request: Request) -> dict:
    """修改密碼：先驗證舊密碼，再經 GoTrue 更新（配合前端 E2EE 密鑰遷移）。"""
    import httpx as _httpx

    if len(payload.new_password) < 6:
        raise HTTPException(422, "新密碼至少 6 位")
    email = user.get("email")
    # 驗證舊密碼
    try:
        r = _httpx.post(
            f"{settings.supabase_url}/auth/v1/token?grant_type=password",
            headers={"apikey": settings.supabase_anon_key},
            json={"email": email, "password": payload.old_password},
            timeout=20,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"驗證服務不可用: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(401, "舊密碼不正確")
    # 用當前用戶 token 更新密碼
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    r = _httpx.put(
        f"{settings.supabase_url}/auth/v1/user",
        headers={"apikey": settings.supabase_anon_key, "Authorization": f"Bearer {token}"},
        json={"password": payload.new_password},
        timeout=20,
    )
    if r.status_code != 200:
        raise HTTPException(502, f"密碼更新失敗: {r.text[:200]}")
    return {"ok": True, "note": "密碼已更新；敏感字段密文已由前端用新密鑰重新加密"}
