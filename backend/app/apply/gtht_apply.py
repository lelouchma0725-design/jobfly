"""國泰海通證券投遞適配器（hr.gtht.com，純 HTTP API，無需瀏覽器）。

流程（2026-10 實測站點結構）：
1. 登錄 POST /api/login/account.json {account, password} → data.token
   （登錄頁有極驗驗證碼；自動化登錄被攔截時轉人工接管）
2. 申請 POST /api/user/applyJob.json?stamp=… {job_id} + header token
3. 失敗信息若涉及簡歷 → 人工接管提示先到官網完善簡歷（一次性）
"""
from __future__ import annotations

import logging
import random
import ssl

import httpx

from app.apply.base import ApplyContext, ApplyResult, ManualRequest, register_adapter

logger = logging.getLogger(__name__)

BASE = "https://hr.gtht.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

SUCCESS_CODES = (200, 0)


def _legacy_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
    return ctx


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
                    "投遞國泰海通需要你的招聘系統帳號：請在「平台帳號」頁添加"
                    "（平台選「國泰海通證券」，帳號/密碼為你註冊 hr.gtht.com 的帳號）",
                    {"confirmed": {"label": "我已添加帳號", "type": "checkbox"}},
                ),
            )
        try:
            client = httpx.Client(
                verify=_legacy_ssl_context(), headers={"User-Agent": UA}, timeout=30,
                base_url=BASE,
            )
            token = self._login(client, ctx)
            if not token:
                return ApplyResult(
                    False, error_code="login_failed",
                    manual=ManualRequest(
                        "login_required",
                        "國泰海通登錄失敗：可能是密碼錯誤，或頁面出現極驗滑塊驗證。"
                        "請檢查「平台帳號」中的帳號密碼；若為驗證碼問題，"
                        "可先用手機/電腦在官網正常登錄一次後再重試本投遞。",
                        {"confirmed": {"label": "已確認帳號密碼正確", "type": "checkbox"}},
                    ),
                )
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

    def _login(self, client: httpx.Client, ctx: ApplyContext) -> str | None:
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
            if data.get("errno") not in (400, 401, 403):
                # 非認證錯誤（如驗證碼要求），記錄信息後返回 None 走人工接管
                logger.info("gtht 登錄未成功: %s", str(data)[:200])
                return None
        return None
