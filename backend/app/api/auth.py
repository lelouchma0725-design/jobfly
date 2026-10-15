"""認證代理（關鍵架構）：前端不直連 supabase.co，全部 auth 請求經後端轉發。

原因：部分地區網絡無法直達 *.supabase.co（實測本網絡連接被重置）。
後端部署於美區（Render），可正常訪問 Supabase Auth API。
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException
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


def _err(resp: httpx.Response) -> str:
    try:
        return resp.json().get("msg") or resp.json().get("error_description") or resp.text[:300]
    except Exception:  # noqa: BLE001
        return resp.text[:300]
