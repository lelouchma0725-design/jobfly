"""個人信息元信息表（投遞表單互補機制）。

- 用戶維護一份「表單問答庫」：key（字段名/問題）→ value
- 投遞遇到表單必填項時：精確 key 命中直接填；相似度 ≥0.5 自動填（記入 attempt trace）
- 人工接管回填的答案自動存庫（source=manual_answer），下次免問
- 與簡歷解析結果互補：簡歷有 → 畫像層；簡歷沒有 → 元信息表 → 問用戶

保護方式：
- 敏感字段由服務端用該用戶的數據密鑰做 AES-256-GCM 字段級加密後落庫（sensitive_enc）
- 列表接口只返回掩碼值；明文僅在「查看」與「填寫方案」按需解密，不批量下發
"""
from __future__ import annotations

import difflib
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.security import decrypt_field, encrypt_field, get_dek_for_user
from app.db import get_db

router = APIRouter(prefix="/me/info-fields", tags=["info-fields"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]


class InfoFieldUpsert(BaseModel):
    key: str
    value: str


class InfoFieldItem(BaseModel):
    key: str
    value: str


class InfoFieldsBatch(BaseModel):
    fields: list[InfoFieldItem]


SENSITIVE_KEY_RE = re.compile(
    r"證件|证件|身份證|身份证|護照|护照|家庭|親屬|亲属|緊急聯繫|紧急联系|"
    r"證件號|证件号|地址|邮编|郵編|電話|电话|手機|手机|姓名拼音|父|母"
)


def _mask_value(v: str) -> str:
    """敏感字段服務器端只存掩碼（列表顯示用），明文不落庫。"""
    if len(v) <= 4:
        return "****"
    return v[:2] + "*" * min(len(v) - 4, 8) + v[-2:]


def _plaintext(db: Session, user_id: str, value: str, enc: str | None) -> str:
    """有密文則解密，否則返回存的明文（非敏感字段）。解密失敗回退掩碼值。"""
    if not enc:
        return value
    try:
        return decrypt_field(get_dek_for_user(db, user_id), enc)
    except Exception:  # noqa: BLE001
        return value


@router.get("")
def list_fields(user: CurrentUser, db: DB) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT key, value, sensitive_enc, source, updated_at FROM user_info_fields "
            "WHERE user_id=:uid ORDER BY updated_at DESC LIMIT 200"
        ),
        {"uid": user["id"]},
    ).mappings().all()
    return [
        {"key": r["key"], "value": r["value"], "source": r["source"],
         "updated_at": r["updated_at"].isoformat(),
         "sensitive": bool(SENSITIVE_KEY_RE.search(r["key"]))}
        for r in rows
    ]


@router.get("/{key}/reveal")
def reveal_field(user: CurrentUser, db: DB, key: str) -> dict:
    """按需查看單個字段明文（僅本人、僅單條），用於「顯示」按鈕。"""
    row = db.execute(
        text("SELECT value, sensitive_enc FROM user_info_fields WHERE user_id=:uid AND key=:k"),
        {"uid": user["id"], "k": key.strip()[:100]},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "字段不存在")
    return {"key": key, "value": _plaintext(db, user["id"], row["value"], row["sensitive_enc"])}


@router.put("")
def upsert_field(user: CurrentUser, db: DB, payload: InfoFieldUpsert) -> dict:
    key = payload.key.strip()[:100]
    value = payload.value.strip()[:2000]
    sensitive = bool(SENSITIVE_KEY_RE.search(key))
    if sensitive:
        enc = encrypt_field(get_dek_for_user(db, user["id"]), value)
        db.execute(
            text(
                """
                INSERT INTO user_info_fields (user_id, key, value, sensitive_enc, source)
                VALUES (:uid, :k, :v, :enc, 'user')
                ON CONFLICT (user_id, key) DO UPDATE
                  SET value=EXCLUDED.value, sensitive_enc=EXCLUDED.sensitive_enc,
                      source='user', updated_at=now()
                """
            ),
            {"uid": user["id"], "k": key, "v": _mask_value(value), "enc": enc[:4000]},
        )
    else:
        db.execute(
            text(
                """
                INSERT INTO user_info_fields (user_id, key, value, source)
                VALUES (:uid, :k, :v, 'user')
                ON CONFLICT (user_id, key) DO UPDATE
                  SET value=EXCLUDED.value, sensitive_enc=NULL,
                      source='user', updated_at=now()
                """
            ),
            {"uid": user["id"], "k": key, "v": value},
        )
    db.commit()
    return {"ok": True, "sensitive": sensitive}


@router.put("/batch")
def upsert_fields_batch(user: CurrentUser, db: DB, payload: InfoFieldsBatch) -> dict:
    """批量寫入（投遞回填 / 資料匯入）：敏感字段由服務端加密後落庫。"""
    saved = 0
    for f in payload.fields:
        key = f.key.strip()[:100]
        if not key:
            continue
        value = f.value.strip()[:2000]
        sensitive = bool(SENSITIVE_KEY_RE.search(key))
        if sensitive:
            enc = encrypt_field(get_dek_for_user(db, user["id"]), value)[:4000]
            stored, mask = _mask_value(value), enc
        else:
            stored, mask = value, None
        db.execute(
            text(
                """
                INSERT INTO user_info_fields (user_id, key, value, sensitive_enc, source)
                VALUES (:uid, :k, :v, :enc, 'website')
                ON CONFLICT (user_id, key) DO UPDATE
                  SET value=EXCLUDED.value,
                      sensitive_enc=COALESCE(EXCLUDED.sensitive_enc, user_info_fields.sensitive_enc),
                      source='website', updated_at=now()
                """
            ),
            {"uid": user["id"], "k": key, "v": stored, "enc": mask},
        )
        saved += 1
    db.commit()
    return {"ok": True, "saved": saved}


@router.delete("/{key}")
def delete_field(user: CurrentUser, db: DB, key: str) -> dict:
    db.execute(
        text("DELETE FROM user_info_fields WHERE user_id=:uid AND key=:k"),
        {"uid": user["id"], "k": key},
    )
    db.commit()
    return {"ok": True}


# ── 相似度解析（供投遞引擎調用）────────────────────────────

def _tokens(s: str) -> set[str]:
    s = re.sub(r"[^\w\u4e00-\u9fff]+", " ", s.lower())
    toks = {t for t in s.split() if len(t) > 1}
    # 中文按單字+雙字組拆
    for w in re.findall(r"[\u4e00-\u9fff]+", s):
        toks.update(w)
        toks.update(w[i:i + 2] for i in range(len(w) - 1))
    return toks


def similarity(a: str, b: str) -> float:
    """字段名/問題的相似度：序列比對 + token 重疊取較大者。"""
    if not a or not b:
        return 0.0
    if a.strip().lower() == b.strip().lower():
        return 1.0
    seq = difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return seq
    overlap = len(ta & tb) / min(len(ta), len(tb))
    return max(seq, overlap)


def resolve_field(db: Session, user_id: str, field_key: str, field_label: str,
                  threshold: float = 0.5) -> tuple[str | None, str | None, float]:
    """為表單字段找答案：精確命中 → 相似度 ≥ 閾值 → 無。

    返回 (value, 來源key, 相似度)；value=None 表示需要詢問用戶。
    敏感字段在此按需解密，保證自動填報拿到的是真實內容而非掩碼。
    """
    rows = db.execute(
        text("SELECT key, value, sensitive_enc, source FROM user_info_fields WHERE user_id=:uid"),
        {"uid": user_id},
    ).mappings().all()
    if not rows:
        return None, None, 0.0

    def plain(r) -> str:
        return _plaintext(db, user_id, r["value"], r["sensitive_enc"])

    # 精確命中（key 或 label 一致）
    for r in rows:
        if r["key"].strip().lower() in (field_key.lower(), field_label.lower()):
            return plain(r), r["key"], 1.0
    # 相似度匹配
    best = max(rows, key=lambda r: max(
        similarity(r["key"], field_key), similarity(r["key"], field_label)))
    score = max(similarity(best["key"], field_key), similarity(best["key"], field_label))
    if score >= threshold:
        return plain(best), best["key"], round(score, 2)
    return None, None, round(score, 2)


def save_answer(db: Session, user_id: str, key: str, value: str) -> None:
    """人工回填答案自動入庫（投遞引擎調用）；敏感字段同樣加密後落庫。"""
    key = key.strip()[:100]
    value = value.strip()[:2000]
    if SENSITIVE_KEY_RE.search(key):
        enc = encrypt_field(get_dek_for_user(db, user_id), value)
        stored = _mask_value(value)
    else:
        enc, stored = None, value
    db.execute(
        text(
            """
            INSERT INTO user_info_fields (user_id, key, value, sensitive_enc, source)
            VALUES (:uid, :k, :v, :enc, 'manual_answer')
            ON CONFLICT (user_id, key) DO UPDATE
              SET value=EXCLUDED.value,
                  sensitive_enc=COALESCE(EXCLUDED.sensitive_enc, user_info_fields.sensitive_enc),
                  source='manual_answer', updated_at=now()
            """
        ),
        {"uid": user_id, "k": key, "v": stored, "enc": enc},
    )
