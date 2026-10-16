"""中信證券投遞適配器（careers.citics.com）。

登錄機制（實測 2026-10）：
- 發送驗證碼 POST kong.citics.com/api/v2/account/mobile/sendCode
  要求：sysNo=CSE001 + 圖形驗證碼（41213 图形验证码不可为空）
- 圖形驗證碼無法在服務端自動破解 → 採用「持久化登錄態 + 人工接管」：
  1) 首次投遞：引導用戶自行在官網登錄並提交（提供崗位直達鏈接與指引）
  2) 用戶回填確認（可附申請編號）→ 系統記錄為已投遞（人工確認模式）
  3) 未來若拿到 token 登錄接口，_try_auto 會優先自動流程
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import text

from app.apply.base import ApplyContext, ApplyResult, ManualRequest, register_adapter
from app.core.jsonutil import j
from app.core.security import decrypt_json, encrypt_json, get_dek_for_user
from app.db import SessionLocal

logger = logging.getLogger(__name__)

STATE_TTL_DAYS = 14
APPLY_URL = "https://careers.citics.com/campus/branch"


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
        logger.exception("citics 登錄態讀取失敗 user=%s", ctx.user_id)
        return None
    finally:
        db.close()


@register_adapter
class CiticsApplyAdapter:
    name = "citics"

    def apply(self, ctx: ApplyContext) -> ApplyResult:
        state = _load_state(ctx)
        if state and state.get("token"):
            auto = _try_auto_apply(ctx, state["token"])
            if auto:
                return auto

        job_title = (ctx.posting.get("title") or "").strip()
        question = (
            f"中信證券「{job_title}」需要你在官網完成登錄與申請（服務端無法通過圖形驗證碼）：\n"
            "1. 打開 https://careers.citics.com 用手機號登錄（圖形驗證 + 短信碼）\n"
            f"2. 在「校園招聘 → 分支機構」找到「{job_title}」並完成申請\n"
            "3. 完成後回到這裡勾選確認（如有申請編號請填寫）\n"
            "（系統將記錄為已投遞·人工確認；今後同公司投遞會再次嘗試自動化）"
        )
        return ApplyResult(
            False, error_code="manual_citics_login",
            manual=ManualRequest("citics_manual", question, {
                "confirmed": {"label": "我已在官網提交申請", "type": "checkbox"},
                "external_ref": {"label": "申請編號/確認信息（可選）", "type": "text"},
            }),
        )


def _try_auto_apply(ctx: ApplyContext, token: str) -> ApplyResult | None:
    """有 token 時嘗試自動申請（志願接口參數為最佳猜測，失敗返回 None → 人工接管）。"""
    import httpx

    raw = (ctx.posting.get("raw") or {}) or {}
    position_no = str(raw.get("positionNo") or "")
    dept_no = str(raw.get("deptNo") or "")
    if not position_no:
        return None
    try:
        resp = httpx.post(
            f"https://global-kong.citics.com/api/v1/recruit/mobile/saveDeptVoluntaryBatch"
            f"?sysNo=CSE001&token={token}",
            json={
                "deptVoluntaryList": [{
                    "positionNo": position_no,
                    "deptNo": dept_no,
                    "voluntaryNo": "1",
                }]
            },
            headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"},
            timeout=30,
        )
        data = resp.json()
        if data.get("errorCode") in (0, "0"):
            return ApplyResult(True, external_ref=f"citics:{position_no}")
        logger.warning("citics 自動申請接口拒絕: %s", resp.text[:200])
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("citics 自動申請失敗: %s", exc)
        return None


def merge_manual_answer(ctx: ApplyContext, answer: dict) -> dict:
    """人工回填處理：用戶確認已在官網提交 → 標記 submitted。"""
    from app.core.security import encrypt_json, get_dek_for_user

    if answer.get("confirmed"):
        ext = (answer.get("external_ref") or "").strip() or f"manual:{uuid.uuid4().hex[:8]}"
        # 保存狀態（無 token，僅記錄人工確認時間，避免重複詢問）
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
                            {"manual_confirmed_at": __import__("datetime").datetime.now(
                                __import__("datetime").timezone.utc).isoformat()},
                        ),
                        "aid": ctx.account["id"],
                    },
                )
                db.commit()
        finally:
            db.close()
        return {"submitted": True, "external_ref": ext, "mode": "manual_confirmed"}
    return {"submitted": False}
