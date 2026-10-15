"""後台調度器：每日採集 + 心跳保活（FR-3a2/3a3，GAP-9 可靠性）。

- 每日 02:00（Asia/Shanghai）執行 collect_all_users
- 每 6 小時心跳：真實查庫，防止 Supabase Free 因 1 週無活動被休眠
- 單進程模型：與 API 同進程（免費層部署），用 collect_jobs 表做任務留痕
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import text

from app.collectors.pipeline import collect_all_users
from app.db import get_engine

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _job_collect() -> None:
    from app.db import SessionLocal  # 惰性，避免無 DB 配置時啟動失敗

    logger.info("每日採集任務開始")
    db = SessionLocal()
    try:
        db.execute(
            text(
                "INSERT INTO collect_jobs (kind, status, scheduled_at) "
                "VALUES ('collect', 'running', now()) RETURNING id"
            )
        )
        report = collect_all_users(db)
        db.execute(
            text(
                "UPDATE collect_jobs SET status='done', finished_at=now(), payload=CAST(:p AS jsonb) "
                "WHERE kind='collect' AND status='running' AND finished_at IS NULL"
            ),
            {"p": report},
        )
        db.commit()
        logger.info("每日採集完成: %s", report)
    except Exception:  # noqa: BLE001
        logger.exception("每日採集失敗")
        try:
            db.execute(
                text(
                    "UPDATE collect_jobs SET status='failed', finished_at=now() "
                    "WHERE kind='collect' AND status='running' AND finished_at IS NULL"
                )
            )
            db.commit()
        except Exception:  # noqa: BLE001
            pass
    finally:
        db.close()


def _job_heartbeat() -> None:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.debug("心跳 OK")
    except Exception as exc:  # noqa: BLE001
        logger.warning("心跳失敗（數據庫未配置或不可達）: %s", exc)


def _job_daily_push() -> None:
    """每 10 分鐘掃描：到達用戶設定推送時間（本地時區）且當日未發 → 發每日摘要。"""
    from app.db import SessionLocal
    from app.services.digest import deliver_daily_digest

    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                SELECT user_id FROM user_settings s
                WHERE s.daily_digest_enabled = true
                  AND to_char(now() AT TIME ZONE s.timezone, 'HH24:MI') = to_char(s.push_time_local, 'HH24:MI')
                  AND NOT EXISTS (
                    SELECT 1 FROM notifications n
                    WHERE n.user_id = s.user_id AND n.kind = 'daily_digest'
                      AND n.sent_at >= (now() AT TIME ZONE s.timezone)::date
                  )
                """
            )
        ).mappings().all()
        for r in rows:
            try:
                deliver_daily_digest(db, str(r["user_id"]))
            except Exception:  # noqa: BLE001
                logger.exception("每日摘要推送失敗 user=%s", r["user_id"])
    finally:
        db.close()


def _job_apply_queue() -> None:
    """每 30 分鐘：處理到期投遞隊列（queued + 到期重試）。"""
    from app.db import SessionLocal
    from app.services.apply_engine import process_queue

    db = SessionLocal()
    try:
        report = process_queue(db)
        if report["processed"]:
            logger.info("投遞隊列處理: %s", report)
    except Exception:  # noqa: BLE001
        logger.exception("投遞隊列處理失敗")
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    _scheduler.add_job(_job_collect, CronTrigger(hour=2, minute=0), id="daily_collect",
                       misfire_grace_time=3600, coalesce=True, max_instances=1)
    _scheduler.add_job(_job_daily_push, IntervalTrigger(minutes=10), id="daily_push",
                       coalesce=True, max_instances=1)
    _scheduler.add_job(_job_apply_queue, IntervalTrigger(minutes=30), id="apply_queue",
                       coalesce=True, max_instances=1)
    _scheduler.add_job(_job_heartbeat, IntervalTrigger(hours=6), id="heartbeat",
                       coalesce=True, max_instances=1)
    _scheduler.start()
    logger.info("調度器已啟動（每日採集 02:00 + 摘要推送 10min + 投遞隊列 30min + 心跳 6h）")
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
