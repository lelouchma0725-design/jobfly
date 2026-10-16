"""國泰海通證券投遞適配器（hr.gtht.com，純 HTTP API）。

登錄策略（三級降級）：
1. 已保存的登錄 token（cookie_state_enc 加密持久化，過期前免驗證）
2. 帳號密碼登錄 POST /api/login/account.json
3. 短信驗證碼登錄 POST /api/login/codelogin.json —— 需要用戶在官網
   點擊「發送驗證碼」（登錄頁有極驗滑塊），收到後把 6 位驗證碼回填
   「待處理」任務 → 系統登錄成功後保存 token，之後長時間免驗證。

申請：POST /api/user/applyJob.json?stamp=… {job_id} + header token。
"""
from __future__ import annotations

import datetime as dt
import logging
import random
import ssl

import httpx
from sqlalchemy import text

from app.apply.base import ApplyContext, ApplyResult, ManualRequest, register_adapter
from app.core.security import decrypt_json, encrypt_json, get_dek_for_user
from app.db import SessionLocal

logger = logging.getLogger(__name__)

BASE = "https://hr.gtht.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

SUCCESS_CODES = (200, 0)
STATE_TTL_DAYS = 14  # token 過期閾值（超出視為失效，重新走驗證）


def _legacy_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
    return ctx


def _load_state(ctx: ApplyContext) -> dict | None:
    """讀取加密持久化的登錄態（token + 保存時間）。"""
    db = SessionLocal()
    try:
        row = db.execute(
            text(
                "SELECT cookie_state_enc FROM platform_accounts WHERE id=:aid"
            ),
            {"aid": ctx.account.get("id")},
        ).first()
        if not row or not row[0]:
            return None
        state = decrypt_json(get_dek_for_user(db, ctx.user_id), row[0])
        saved = state.get("saved_at")
        if saved:
            age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(saved)).days
            if age > STATE_TTL_DAYS:
                return None
        return state
    except Exception:  # noqa: BLE001
        logger.exception("gtht 登錄態讀取失敗 user=%s", ctx.user_id)
        return None
    finally:
        db.close()


def _save_state(ctx: ApplyContext, token: str) -> None:
    state = {"token": token, "saved_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    db = SessionLocal()
    try:
        db.execute(
            text(
                "UPDATE platform_accounts SET cookie_state_enc=:s, status='active', "
                "last_login_at=now(), updated_at=now() WHERE id=:aid"
            ),
            {"s": encrypt_json(get_dek_for_user(db, ctx.user_id), state),
             "aid": ctx.account.get("id")},
        )
        db.commit()
    finally:
        db.close()


@register_adapter
class GthtApplyAdapter:
    name = "gtht"

    def apply(self, ctx: ApplyContext) -> ApplyResult:
        if ctx.dry_run:
            return ApplyResult(True, external_ref="DRY_RUN")
        if not ctx.account:
            return ApplyResult(
                False, error_code="login_required",
                manual=ManualRequest(
                    "login_required",
                    "投遞國泰海通需要你的招聘系統帳號：請在「我的資料→平台帳號」添加"
                    "（平台選「國泰海通證券」，帳號填註冊手機號，密碼留空或填網站密碼）",
                    {"confirmed": {"label": "我已添加帳號", "type": "checkbox"}},
                ),
            )
        try:
            client = httpx.Client(
                verify=_legacy_ssl_context(), headers={"User-Agent": UA},
                timeout=30, base_url=BASE,
            )
            token = self._get_token(client, ctx)
            if not token:
                return self._sms_manual()
            job_id = ctx.posting.get("external_id")
            resp = client.post(
                f"/api/user/applyJob.json?stamp={random.random()}",
                data={"job_id": job_id},
                headers={"token": token},
            )
            data = resp.json()
            errno = data.get("errno")
            message = str(data.get("message") or data.get("msg") or "")
            if errno in SUCCESS_CODES:
                return ApplyResult(True, external_ref=f"gtht:{job_id}")
            if "登录" in message or "登錄" in message or errno in (401, 403):
                # token 失效 → 清掉舊狀態，讓下次走驗證碼流程
                _clear_state(ctx)
                return self._sms_manual()
            if "简历" in message or "簡歷" in message:
                return ApplyResult(
                    False, error_code="resume_required",
                    manual=ManualRequest(
                        "confirm_content",
                        "國泰海通系統要求先在其官網完善你的在線簡歷（一次性）："
                        "請登錄 https://hr.gtht.com 完成簡歷填寫，之後點擊確認自動重投。",
                        {"confirmed": {"label": "已在官網完善簡歷", "type": "checkbox"}},
                    ),
                )
            if "已申请" in message or "已申請" in message:
                return ApplyResult(True, external_ref=f"gtht:{job_id}:duplicate")
            return ApplyResult(
                False, error_code="apply_rejected",
                error_detail=message[:500] or f"errno={errno}",
                manual=ManualRequest(
                    "confirm_content",
                    f"國泰海通投遞返回：{message or f'errno={errno}'}。"
                    "請確認崗位是否開放/條件是否滿足，或補充說明後重試。",
                    {"note": {"label": "補充說明（可空）", "type": "text"},
                     "confirmed": {"label": "已確認可投遞", "type": "checkbox"}},
                ),
            )
        except httpx.HTTPError as exc:
            logger.exception("gtht 投遞網絡錯誤 app=%s", ctx.application_id)
            return ApplyResult(False, error_code="adapter_error",
                               error_detail=str(exc)[:300])
        except Exception as exc:  # noqa: BLE001
            logger.exception("gtht 投遞異常 app=%s", ctx.application_id)
            return ApplyResult(False, error_code="adapter_error",
                               error_detail=str(exc)[:300])

    def _get_token(self, client: httpx.Client, ctx: ApplyContext) -> str | None:
        # 1) 持久化 token 優先（免驗證）
        state = _load_state(ctx)
        if state and state.get("token"):
            return state["token"]
        # 2) 短信驗證碼（用戶在「待處理」回填的 sms_code）
        sms_code = (ctx.payload or {}).get("sms_code")
        if sms_code:
            token = self._login_with_code(client, ctx, sms_code)
            if token:
                _save_state(ctx, token)
                return token
        # 3) 帳號密碼登錄
        token = self._login_with_password(client, ctx)
        if token:
            _save_state(ctx, token)
        return token

    def _login_with_password(self, client: httpx.Client, ctx: ApplyContext) -> str | None:
        if not ctx.account.get("password"):
            return None
        for params in (
            {"account": ctx.account["login"], "password": ctx.account["password"]},
            {"username": ctx.account["login"], "password": ctx.account["password"]},
        ):
            resp = client.post("/api/login/account.json", data=params)
            try:
                data = resp.json()
            except Exception:  # noqa: BLE001
                continue
            if data.get("errno") in SUCCESS_CODES and (data.get("data") or {}).get("token"):
                return data["data"]["token"]
            logger.info("gtht 密碼登錄未成功: %s", str(data)[:200])
            return None
        return None

    def _login_with_code(self, client: httpx.Client, ctx: ApplyContext, code: str) -> str | None:
        for params in (
            {"mobile": ctx.account["login"], "code": code},
            {"phone": ctx.account["login"], "code": code},
        ):
            resp = client.post("/api/login/codelogin.json", data=params)
            try:
                data = resp.json()
            except Exception:  # noqa: BLE001
                continue
            if data.get("errno") in SUCCESS_CODES and (data.get("data") or {}).get("token"):
                return data["data"]["token"]
            logger.info("gtht 驗證碼登錄未成功: %s", str(data)[:200])
            return None
        return None

    def _sms_manual(self) -> ApplyResult:
        return ApplyResult(
            False, error_code="sms_code_required",
            manual=ManualRequest(
                "captcha",
                "國泰海通需要短信驗證碼登錄（一次性，登錄態將保存約兩週）：\n"
                "1. 用手機或電腦打開 https://hr.gtht.com/login\n"
                "2. 輸入你註冊的手機號，點擊「獲取驗證碼」（如有滑塊驗證請完成）\n"
                "3. 把收到的 6 位短信驗證碼填入下方 → 提交後系統自動登錄並繼續投遞",
                {"sms_code": {"label": "短信驗證碼（6位數字）", "type": "text"}},
            ),
        )


def _clear_state(ctx: ApplyContext) -> None:
    db = SessionLocal()
    try:
        db.execute(
            text(
                "UPDATE platform_accounts SET cookie_state_enc=NULL, status='expired', "
                "updated_at=now() WHERE id=:aid"
            ),
            {"aid": ctx.account.get("id")},
        )
        db.commit()
    finally:
        db.close()
