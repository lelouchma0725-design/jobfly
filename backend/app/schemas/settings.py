"""用戶設置的請求模型（FR-1c/1f/1g/1h）。"""
from __future__ import annotations

from datetime import time
from typing import Literal

from pydantic import BaseModel, Field, field_validator

AutoApplyMode = Literal["off", "threshold", "all"]


class SettingsUpdate(BaseModel):
    """PATCH /api/me/settings：全部可選，僅更新傳入字段。"""

    ai_optimize_resume: bool | None = None
    ai_optimize_cover_letter: bool | None = None
    match_threshold: int | None = Field(default=None, ge=50, le=100)
    auto_apply_mode: AutoApplyMode | None = None
    apply_rate_limit_min: int | None = Field(default=None, ge=1, le=120)
    push_time_local: time | None = None
    timezone: str | None = None
    daily_digest_enabled: bool | None = None
    login_expiry_notify: bool | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        if v is None:
            return v
        import zoneinfo

        zoneinfo.ZoneInfo(v)  # 非法時區直接拋錯
        return v
