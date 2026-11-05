"""每日摘要（FR-3a3）：新匹配崗位 + 投遞結果 + 待人工處理 + 登錄態提醒。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.services.notifier import notify_with_fallback

TODAY_CUTOFF = 24  # 「今日新匹配」窗口（小時）


def build_daily_digest(db: Session, user_id: str) -> str | None:
    """生成 markdown 摘要；無內容返回 None。"""
    st = db.execute(
        text(
            "SELECT match_threshold, auto_apply_mode FROM user_settings WHERE user_id=:uid"
        ),
        {"uid": user_id},
    ).mappings().first()
    threshold = st["match_threshold"] if st else 70

    since = datetime.now(timezone.utc) - timedelta(hours=TODAY_CUTOFF)
    matches = db.execute(
        text(
            """
            SELECT p.company_name, p.title, p.location, m.match_score, p.apply_url
            FROM job_matches m JOIN job_postings p ON p.id = m.posting_id
            WHERE m.user_id=:uid AND m.status IN ('new','pushed')
              AND m.match_score >= :th AND p.is_active=true
            ORDER BY m.match_score DESC LIMIT 10
            """
        ),
        {"uid": user_id, "th": threshold},
    ).mappings().all()

    apps = db.execute(
        text(
            """
            SELECT status, COUNT(*) AS n FROM applications
            WHERE user_id=:uid AND updated_at >= now() - interval '24 hours'
            GROUP BY status
            """
        ),
        {"uid": user_id},
    ).mappings().all()

    tasks = db.execute(
        text(
            """
            SELECT COUNT(*) AS n FROM manual_tasks
            WHERE user_id=:uid AND status='open'
            """
        ),
        {"uid": user_id},
    ).mappings().one()

    expiring = db.execute(
        text(
            """
            SELECT platform, label FROM platform_accounts
            WHERE user_id=:uid AND status IN ('expired','error','locked')
            """
        ),
        {"uid": user_id},
    ).mappings().all()

    parts: list[str] = []
    if matches:
        parts.append("### 🎯 新匹配崗位")
        for m in matches:
            parts.append(
                f"- **{m['company_name']} · {m['title']}**（{m['location'] or '地點未標'}）"
                f" 貼合度 {m['match_score']}%\n  [查看/投遞]({settings.frontend_url}/matches)"
            )
    if apps:
        status_text = {"submitted": "✅ 投遞成功", "failed_retryable": "⚠️ 投遞失敗待重試",
                       "needs_input": "✋ 等待你補充信息", "in_progress": "⏳ 投遞中",
                       "queued": "🕐 排隊中"}
        parts.append("### 📬 24 小時投遞結果")
        for a in apps:
            parts.append(f"- {status_text.get(a['status'], a['status'])}：{a['n']} 個")
    if tasks["n"]:
        parts.append(f"### ✋ 待你處理：{tasks['n']} 項人工任務")
        parts.append(f"[立即處理]({settings.frontend_url}/tasks)")
    if expiring:
        parts.append("### 🔐 平台登錄態異常")
        for e in expiring[:5]:
            parts.append(f"- {e['platform']}「{e['label']}」需要重新登錄")
        parts.append(f"[去處理]({settings.frontend_url}/accounts)")
    if not parts:
        return None
    header = "☀️ JobsComing 每日求職報告"
    return header + "\n\n" + "\n\n".join(parts)


def deliver_daily_digest(db: Session, user_id: str) -> dict:
    content = build_daily_digest(db, user_id)
    if not content:
        return {"sent": False, "reason": "無可推送內容"}
    return {
        "sent": True,
        "results": notify_with_fallback(
            db, user_id, "daily_digest", "JobsComing 每日求職報告", content,
            meta={"source": "daily_digest"},
        ),
    }
