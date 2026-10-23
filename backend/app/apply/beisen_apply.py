"""中金公司（北森 zhiye/hotjob 門戶）投遞適配器。

登錄機制與中信類似：門戶登錄需要短信驗證碼（可能含圖形驗證），服務端無法自動完成。
流程：檢查持久化登錄態 → 無則人工接管（用戶在門戶登錄並申請，勾選確認後系統記錄已投遞）。
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import text

from app.apply.base import ApplyContext, ApplyResult, ManualRequest, register_adapter
from app.core.security import decrypt_json, encrypt_json, get_dek_for_user
from app.db import SessionLocal

logger = logging.getLogger(__name__)


def _load_state(ctx: ApplyContext) -> dict | None:
    db = SessionLocal()
    try:
        if not (ctx.account or {}).get("id"):
            return None
        row = db.execute(
            text("SELECT cookie_state_enc FROM platform_accounts WHERE id=:aid"),
            {"aid": ctx.account["id"]},
        ).first()
        if not row or not row[0]:
            return None
        return decrypt_json(get_dek_for_user(db, ctx.user_id), row[0])
    except Exception:  # noqa: BLE001
        logger.exception("beisen 登錄態讀取失敗 user=%s", ctx.user_id)
        return None
    finally:
        db.close()


@register_adapter
class BeisenApplyAdapter:
    name = "beisen"

    def apply(self, ctx: ApplyContext) -> ApplyResult:
        state = _load_state(ctx)
        if state and state.get("token"):
            # 登錄態可用時嘗試自動申請（門戶 API 需 token，尚未完全逆向 → 仍走人工確認）
            pass

        job_title = (ctx.posting.get("title") or "").strip()
        apply_url = ctx.posting.get("apply_url") or ""
        payload = ctx.payload or {}
        skills = ", ".join(s["name"] for s in (payload.get("skills") or []))
        exp_lines = [
            f"{e.get('start')} ~ {e.get('end')} {e.get('company')} {e.get('title')}"
            for e in (payload.get("experiences") or [])[:5]
        ]
        edu_lines = [
            f"{e.get('school')} {e.get('degree')} {e.get('major')}"
            for e in (payload.get("education") or [])
        ]
        fill_block = (
            "📋 填寫方案（複製到門戶對應欄位）：\n"
            f"姓名：{payload.get('full_name') or '（未填）'}\n"
            f"手機：{payload.get('phone') or '（未填）'}\n"
            f"郵箱：{payload.get('email') or '（未填）'}\n"
            f"簽證狀態：{payload.get('visa_status') or '（未填）'}\n"
            f"期望薪資：{payload.get('salary_expectation') or '（未填）'}\n"
            f"技能：{skills or '（未填）'}\n"
            f"工作經歷：\n" + ("\n".join(exp_lines) or "（未填）") + "\n"
            f"教育：{'；'.join(edu_lines) or '（未填）'}"
        )
        question = (
            f"中金公司「{job_title}」需要你在招聘門戶完成登錄與申請"
            "（短信驗證碼只能由你本人完成）：\n"
            f"1. 打開 {apply_url} 用手機號登錄（短信驗證碼）\n"
            f"2. 找到「{job_title}」完成申請（可用 RPA 助手一鍵填報）\n"
            "3. 完成後回到這裡勾選確認（如有申請編號請填寫）\n"
            f"{fill_block}"
        )
        return ApplyResult(
            False, error_code="manual_beisen_login",
            manual=ManualRequest("beisen_manual", question, {
                "confirmed": {"label": "我已在門戶提交申請", "type": "checkbox"},
                "external_ref": {"label": "申請編號/確認信息（可選）", "type": "text"},
            }),
        )


def merge_manual_answer(ctx: ApplyContext, answer: dict) -> dict:
    """人工回填：用戶確認已在門戶提交 → 標記 submitted。"""
    if answer.get("confirmed"):
        ext = (answer.get("external_ref") or "").strip() or f"manual:{uuid.uuid4().hex[:8]}"
        db = SessionLocal()
        try:
            if (ctx.account or {}).get("id"):
                db.execute(
                    text(
                        "UPDATE platform_accounts SET cookie_state_enc=:s, status='active', "
                        "last_login_at=now(), updated_at=now() WHERE id=:aid"
                    ),
                    {
                        "s": encrypt_json(
                            get_dek_for_user(db, ctx.user_id),
                            {"manual_confirmed_at": None}),
                        "aid": ctx.account["id"],
                    },
                )
                db.commit()
        finally:
            db.close()
        return {"submitted": True, "external_ref": ext, "mode": "manual_confirmed"}
    return {"submitted": False}
