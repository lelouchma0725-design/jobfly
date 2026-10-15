"""平台帳號的請求模型（FR-1d）。明文只在請求體中出現，落庫即加密。"""
from __future__ import annotations

from pydantic import BaseModel, Field

PLATFORMS = (
    "workday", "greenhouse", "lever", "successfactors", "icims", "official",
    "liepin", "boss", "lagou", "zhilian", "job51", "linkedin", "indeed", "other",
)


class AccountCreate(BaseModel):
    platform: str
    label: str = Field(min_length=1, max_length=64)
    login_identifier: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=1, max_length=512)
    meta: dict | None = None


class AccountUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=64)
    login_identifier: str | None = Field(default=None, min_length=1, max_length=512)
    password: str | None = Field(default=None, min_length=1, max_length=512)
    meta: dict | None = None


class WatchedCompanyCreate(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    aliases: list[str] | None = None
    careers_url: str | None = None
    platform: str = "official"
    notes: str | None = None


class WatchedCompanyUpdate(BaseModel):
    company_name: str | None = None
    aliases: list[str] | None = None
    careers_url: str | None = None
    platform: str | None = None
    notes: str | None = None
    is_active: bool | None = None
