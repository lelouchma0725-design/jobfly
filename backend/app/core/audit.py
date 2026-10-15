"""審計日誌工具（不影響主流程，失敗僅告警）。"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.jsonutil import j

logger = logging.getLogger(__name__)


def log_audit(
    db: Session,
    actor_user_id: str,
    action: str,
    entity: str | None = None,
    entity_id: str | None = None,
    meta: dict | None = None,
    ip: str | None = None,
) -> None:
    try:
        db.execute(
            text(
                """
                INSERT INTO audit_logs (actor_user_id, action, entity, entity_id, meta, ip)
                VALUES (:a, :action, :e, :eid, CAST(:meta AS jsonb), :ip)
                """
            ),
            {
                "a": actor_user_id,
                "action": action,
                "e": entity,
                "eid": entity_id,
                "meta": j(meta or {}),
                "ip": ip,
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("審計日誌寫入失敗")
