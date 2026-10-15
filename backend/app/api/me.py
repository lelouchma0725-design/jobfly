"""個人資料與設置端點（FR-1a/1c/1f/1g/1h）。

全部端點經 get_current_user 注入當前用戶，多租戶隔離雙重保證：
1) 代碼層強制 user_id = 當前用戶
2) 數據庫層 RLS（見 alembic/versions/0001_initial.py）
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.security import decrypt_field, encrypt_field, get_dek_for_user
from app.db import get_db
from app.schemas.settings import SettingsUpdate
from pydantic import BaseModel

router = APIRouter(tags=["me"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]


class PushChannelUpdate(BaseModel):
    value: str | None = None


@router.get("/me")
def read_me(user: CurrentUser) -> dict:
    return user


@router.get("/me/settings")
def read_settings(user: CurrentUser, db: DB) -> dict:
    row = db.execute(
        text(
            """
            INSERT INTO user_settings (user_id)
            VALUES (:uid)
            ON CONFLICT (user_id) DO NOTHING
            """
        ),
        {"uid": user["id"]},
    )
    db.commit()
    result = db.execute(
        text("SELECT * FROM user_settings WHERE user_id = :uid"),
        {"uid": user["id"]},
    ).mappings().one()
    return _row_to_dict(result)


@router.patch("/me/settings")
def update_settings(user: CurrentUser, db: DB, payload: SettingsUpdate) -> dict:
    fields = payload.model_dump(exclude_none=True)
    if not fields:
        return read_settings(user, db)
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    db.execute(
        text(
            f"""
            INSERT INTO user_settings (user_id)
            VALUES (:uid)
            ON CONFLICT (user_id) DO NOTHING
            """
        ),
        {"uid": user["id"]},
    )
    db.execute(
        text(f"UPDATE user_settings SET {set_clause}, updated_at = now() WHERE user_id = :uid"),
        {"uid": user["id"], **fields},
    )
    db.commit()
    return read_settings(user, db)


@router.get("/me/push-channels")
def read_push_channels(user: CurrentUser, db: DB) -> dict:
    """返回已配置渠道及掩碼值。"""
    row = db.execute(
        text("SELECT push_channels FROM user_settings WHERE user_id = :uid"),
        {"uid": user["id"]},
    ).mappings().first()
    channels = (row["push_channels"] if row else None) or {}
    result = {}
    for channel, key in (("pushplus", "pushplus_token_enc"),
                         ("wecom", "wecom_webhook_enc"), ("email", "email_enc")):
        enc = channels.get(key)
        if not enc:
            continue
        try:
            value = decrypt_field(get_dek_for_user(db, user["id"]), enc)
            result[channel] = _mask_value(channel, value)
        except Exception:  # noqa: BLE001
            result[channel] = "***（解密失敗，請重新配置）"
    return result


@router.patch("/me/push-channels")
def update_push_channel(
    user: CurrentUser, db: DB, channel: str, payload: PushChannelUpdate
) -> dict:
    """配置/清除推送渠道（FR-1h）。value 為 null 表示清除。"""
    value = payload.value
    if channel not in ("pushplus", "wecom", "email"):
        raise HTTPException(422, "channel 必須是 pushplus/wecom/email 之一")
    dek = get_dek_for_user(db, user["id"])
    db.execute(
        text(
            "INSERT INTO user_settings (user_id) VALUES (:uid) ON CONFLICT (user_id) DO NOTHING"
        ),
        {"uid": user["id"]},
    )
    key = {"pushplus": "pushplus_token_enc", "wecom": "wecom_webhook_enc", "email": "email_enc"}[channel]
    if value is None:
        db.execute(
            text(
                "UPDATE user_settings SET push_channels = "
                "COALESCE(push_channels, '{}'::jsonb) - :key, updated_at = now() "
                "WHERE user_id = :uid"
            ),
            {"key": key, "uid": user["id"]},
        )
    else:
        enc = encrypt_field(dek, value)
        db.execute(
            text(
                "UPDATE user_settings SET push_channels = "
                "jsonb_set(COALESCE(push_channels, '{}'::jsonb), :key, to_jsonb(:enc::text)), "
                "updated_at = now() WHERE user_id = :uid"
            ),
            {"key": "{" + key + "}", "enc": enc, "uid": user["id"]},
        )
    db.commit()
    return read_push_channels(user, db)


def _mask_value(channel: str, value: str) -> str:
    if channel == "email":
        at = value.find("@")
        if at > 2:
            return value[:2] + "***" + value[at:]
        return "***@***"
    if len(value) <= 6:
        return "***"
    return value[:3] + "***" + value[-2:]


def _row_to_dict(row) -> dict:
    d = dict(row)
    d.pop("user_id", None)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d
