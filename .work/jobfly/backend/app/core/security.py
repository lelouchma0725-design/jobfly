"""信封加密（Envelope Encryption）——第三方平台帳密與登錄態的安全存儲。

方案（對應《01-架構設計》第 5 節）：
- 每用戶一把 DEK（Data Encryption Key，AES-256-GCM 隨機生成）
- DEK 用服務端 KEK（環境變量，不入庫）包裹後存 key_wraps 表
- 明文只存在於投遞 Worker 進程內存，永不落庫、不落日誌
"""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings

_NONCE_BYTES = 12


def _kek() -> bytes:
    raw = base64.b64decode(settings.kek_base64)
    if len(raw) != 32:
        raise RuntimeError("KEK_BASE64 必須為 32 字節的 base64（openssl rand -base64 32）")
    return raw


def _b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64d(data: str) -> bytes:
    return base64.b64decode(data.encode("ascii"))


def generate_dek() -> bytes:
    """生成用戶 DEK（32 字節）。"""
    return os.urandom(32)


def wrap_dek(dek: bytes) -> str:
    """用 KEK 包裹 DEK 後存庫。"""
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_kek()).encrypt(nonce, dek, None)
    return _b64e(nonce + ciphertext)


def unwrap_dek(wrapped: str) -> bytes:
    """解包 DEK（僅在需要解密用戶數據時調用）。"""
    blob = _b64d(wrapped)
    nonce, ciphertext = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
    return AESGCM(_kek()).decrypt(nonce, ciphertext, None)


def encrypt_field(dek: bytes, plaintext: str) -> str:
    """用用戶 DEK 加密單個字段，輸出 `nonce:ciphertext` base64。"""
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(dek).encrypt(nonce, plaintext.encode("utf-8"), None)
    return _b64e(nonce) + ":" + _b64e(ciphertext)


def decrypt_field(dek: bytes, stored: str) -> str:
    nonce_b64, ciphertext_b64 = stored.split(":", 1)
    return AESGCM(dek).decrypt(_b64d(nonce_b64), _b64d(ciphertext_b64), None).decode("utf-8")


def encrypt_json(dek: bytes, obj: dict) -> str:
    """加密 JSON 結構（如登錄態 Cookie 快照）。"""
    import json

    return encrypt_field(dek, json.dumps(obj, ensure_ascii=False))


def decrypt_json(dek: bytes, stored: str) -> dict:
    import json

    return json.loads(decrypt_field(dek, stored))


def get_dek_for_user(db, user_id: str) -> bytes:
    """取用戶 DEK；不存在則生成並包裹存庫（key_wraps）。"""
    from sqlalchemy import text

    row = db.execute(
        text(
            "SELECT wrapped_dek FROM key_wraps "
            "WHERE owner_type = 'user' AND owner_id = :uid"
        ),
        {"uid": user_id},
    ).mappings().first()
    if row:
        return unwrap_dek(row["wrapped_dek"])
    dek = generate_dek()
    db.execute(
        text(
            "INSERT INTO key_wraps (owner_type, owner_id, wrapped_dek) "
            "VALUES ('user', :uid, :wrapped)"
        ),
        {"uid": user_id, "wrapped": wrap_dek(dek)},
    )
    db.commit()
    return dek
