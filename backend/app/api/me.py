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
from app.core.jsonutil import j
from app.core.security import decrypt_field, encrypt_field, get_dek_for_user
from app.db import get_db
from app.schemas.settings import SettingsUpdate
from pydantic import BaseModel

router = APIRouter(tags=["me"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]


class PushChannelUpdate(BaseModel):
    value: str | None = None


class HardFactUpdate(BaseModel):
    key: str
    value: str | None = None


HARD_FACT_KEYS = {
    "visa_status", "preferred_locations", "salary_expectation", "availability", "total_years",
}


@router.put("/me/hard-facts")
def update_hard_fact(user: CurrentUser, db: DB, payload: HardFactUpdate) -> dict:
    """更新硬性事實：同步寫入畫像 hard_facts 與元信息表（兩處保持一致）。"""
    if payload.key not in HARD_FACT_KEYS:
        raise HTTPException(422, f"key 必須是 {sorted(HARD_FACT_KEYS)} 之一")
    key, value = payload.key, (payload.value or "").strip()
    # 1) 畫像 hard_facts
    db.execute(
        text(
            "UPDATE candidate_profiles SET hard_facts = "
            "jsonb_set(COALESCE(hard_facts, '{}'::jsonb), :k, to_jsonb(:v::text)) "
            "WHERE user_id=:uid AND is_current=true"
        ),
        {"k": "{" + key + "}", "v": value, "uid": user["id"]},
    )
    # 2) 元信息表同步
    db.execute(
        text(
            """
            INSERT INTO user_info_fields (user_id, key, value, source)
            VALUES (:uid, :k, :v, 'user')
            ON CONFLICT (user_id, key) DO UPDATE
              SET value=EXCLUDED.value, source='user', updated_at=now()
            """
        ),
        {"uid": user["id"], "k": key, "v": value},
    )
    db.commit()
    return {"ok": True}


class ProfileUpdate(BaseModel):
    full_name: str | None = None
    phone: str | None = None


@router.get("/me")
def read_me(user: CurrentUser) -> dict:
    return user


@router.patch("/me")
def update_me(user: CurrentUser, db: DB, payload: ProfileUpdate) -> dict:
    """更新個人資料（暱稱/電話）。"""
    if payload.full_name is not None:
        db.execute(
            text("UPDATE profiles SET full_name=:n, updated_at=now() WHERE id=:id"),
            {"n": payload.full_name.strip()[:64], "id": user["id"]},
        )
        user["full_name"] = payload.full_name.strip()[:64]
    if payload.phone is not None:
        db.execute(
            text("UPDATE profiles SET phone=:p, updated_at=now() WHERE id=:id"),
            {"p": payload.phone.strip()[:32], "id": user["id"]},
        )
        user["phone"] = payload.phone.strip()[:32]
    db.commit()
    return user


@router.get("/me/profile-full")
def profile_full(user: CurrentUser, db: DB) -> dict:
    """個人信息總覽：基本信息 + 畫像硬性事實/教育/經歷/技能 + 元信息表，供用戶檢查編輯。"""
    cp = db.execute(
        text(
            "SELECT hard_facts, education, experiences, skills, summary, generated_at "
            "FROM candidate_profiles WHERE user_id=:uid AND is_current=true "
            "ORDER BY generated_at DESC LIMIT 1"
        ),
        {"uid": user["id"]},
    ).mappings().first()
    fields = db.execute(
        text(
            "SELECT key, value, source, updated_at FROM user_info_fields "
            "WHERE user_id=:uid ORDER BY updated_at DESC LIMIT 200"
        ),
        {"uid": user["id"]},
    ).mappings().all()
    return {
        "basic": {
            "full_name": user.get("full_name"),
            "email": user.get("email"),
            "phone": user.get("phone"),
        },
        "profile": {
            "hard_facts": (cp["hard_facts"] if cp else None) or {},
            "education": (cp["education"] if cp else None) or [],
            "experiences": (cp["experiences"] if cp else None) or [],
            "skills": (cp["skills"] if cp else None) or [],
            "summary": (cp["summary"] if cp else None),
            "generated_at": cp["generated_at"].isoformat() if cp and cp["generated_at"] else None,
        },
        "info_fields": [
            {"key": r["key"], "value": r["value"], "source": r["source"],
             "updated_at": r["updated_at"].isoformat()}
            for r in fields
        ],
    }


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
    if "preferred_locations" in fields:
        fields["preferred_locations"] = j(fields["preferred_locations"] or [])
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
