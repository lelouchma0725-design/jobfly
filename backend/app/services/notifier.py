"""通知服務（FR-1h / FR-3c）：PushPlus / 企業微信 / 郵箱三渠道分發。

- 渠道憑據加密存於 user_settings.push_channels（信封加密，見 accounts.py）
- 每次發送先在 notifications 表留痕，失敗標記並降級下一渠道
- 內容統一 markdown，各渠道按需轉換
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import decrypt_field, get_dek_for_user

logger = logging.getLogger(__name__)

CHANNELS = ("pushplus", "wecom", "email")
# 渠道 → push_channels JSONB 中的密文 key
CHANNEL_KEYS = {"pushplus": "pushplus_token_enc", "wecom": "wecom_webhook_enc", "email": "email_enc"}


def resolve_channel_value(db: Session, user_id: str, channel: str) -> str | None:
    """解出用戶某渠道的明文憑據。"""
    row = db.execute(
        text("SELECT push_channels FROM user_settings WHERE user_id=:uid"),
        {"uid": user_id},
    ).mappings().first()
    channels = row["push_channels"] if row else None
    if not channels:
        return None
    key = CHANNEL_KEYS[channel]
    enc = channels.get(key)
    if not enc:
        return None
    try:
        return decrypt_field(get_dek_for_user(db, user_id), enc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("渠道憑據解密失敗 user=%s channel=%s: %s", user_id, channel, exc)
        return None


def send_pushplus(token: str, title: str, content: str) -> None:
    resp = httpx.post(
        "https://www.pushplus.plus/send",
        json={"token": token, "title": title, "content": content, "template": "markdown"},
        timeout=15,
    )
    data = resp.json()
    if data.get("code") != 200:
        raise RuntimeError(f"PushPlus 返回錯誤: {data.get('msg') or data}")


def send_wecom(webhook: str, title: str, content: str) -> None:
    resp = httpx.post(
        webhook,
        json={"msgtype": "markdown", "markdown": {"content": f"## {title}\n{content}"}},
        timeout=15,
    )
    data = resp.json()
    if data.get("errcode") not in (0, None):
        raise RuntimeError(f"企業微信返回錯誤: {data.get('errmsg') or data}")


def send_email(to: str, title: str, content: str) -> None:
    if not (settings.smtp_host and settings.smtp_user and settings.smtp_password):
        raise RuntimeError("SMTP 未配置（SMTP_HOST/SMTP_USER/SMTP_PASSWORD）")
    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = title
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to
    with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15) as server:
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(msg["From"], [to], msg.as_string())


_SENDERS = {"pushplus": send_pushplus, "wecom": send_wecom, "email": send_email}


def notify(
    db: Session,
    user_id: str,
    channel: str,
    kind: str,
    title: str,
    content: str,
    meta: dict | None = None,
) -> dict:
    """發送並留痕。返回 {status, error}。"""
    row = db.execute(
        text(
            """
            INSERT INTO notifications (user_id, channel, kind, title, content, meta)
            VALUES (:uid, :ch, :kind, :t, :c, CAST(:m AS jsonb))
            RETURNING id
            """
        ),
        {"uid": user_id, "ch": channel, "kind": kind, "t": title, "c": content,
         "m": meta or {}},
    ).mappings().one()
    note_id = str(row["id"])
    try:
        value = resolve_channel_value(db, user_id, channel)
        if not value:
            raise RuntimeError(f"用戶未配置渠道 {channel}")
        _SENDERS[channel](value, title, content)
        db.execute(
            text("UPDATE notifications SET status='sent', sent_at=now() WHERE id=:id"),
            {"id": note_id},
        )
        db.commit()
        return {"status": "sent"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("推送失敗 note=%s: %s", note_id, exc)
        db.execute(
            text("UPDATE notifications SET status='failed', error=:e WHERE id=:id"),
            {"id": note_id, "e": str(exc)[:2000]},
        )
        db.commit()
        return {"status": "failed", "error": str(exc)[:500]}


def notify_with_fallback(
    db: Session, user_id: str, kind: str, title: str, content: str, meta: dict | None = None
) -> list[dict]:
    """按用戶配置的渠道順序依次嘗試（pushplus → wecom → email），直到成功。"""
    configured: list[str] = []
    row = db.execute(
        text("SELECT push_channels FROM user_settings WHERE user_id=:uid"),
        {"uid": user_id},
    ).mappings().first()
    channels = (row["push_channels"] if row else None) or {}
    for ch in ("pushplus", "wecom", "email"):
        if channels.get(CHANNEL_KEYS[ch]):
            configured.append(ch)
    if not configured:
        return [{"channel": None, "status": "failed", "error": "用戶未配置任何推送渠道"}]
    results = []
    for ch in configured:
        r = notify(db, user_id, ch, kind, title, content, meta)
        results.append({"channel": ch, **r})
        if r["status"] == "sent":
            break
    return results
