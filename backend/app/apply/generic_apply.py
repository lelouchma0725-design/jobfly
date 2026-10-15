"""通用投遞適配器（Workday / 官網 / 其他未知表單，最佳努力）。

策略：收集表單可見輸入框 → 按 name/placeholder/標籤關鍵詞映射到候選人字段 →
填充 → 上傳簡歷 → 提交 → 成功信號檢測。任何卡點轉人工接管（GAP：不硬來、不編造）。
"""
from __future__ import annotations

import json
import logging

from app.apply.base import ApplyContext, ApplyResult, ManualRequest, register_adapter
from app.apply.browser import (
    detect_captcha,
    human_pause,
    new_stealth_context,
    take_screenshot,
    upload_file,
)

logger = logging.getLogger(__name__)

# 表單字段關鍵詞 → payload 鍵
FIELD_MAP = [
    (("first", "given"), None, "first_name"),
    (("last", "family", "surname"), None, "last_name"),
    (("email",), None, "email"),
    (("phone", "mobile", "tel"), None, "phone"),
    (("city", "location"), None, "location"),
    (("salary", "expected pay", "期望薪资"), None, "salary_expectation"),
    (("available", "start date", "到岗"), None, "availability"),
    (("visa", "work authorization", "签证"), None, "visa_status"),
    (("linkedin",), None, "linkedin_url"),
    (("website", "portfolio", "github"), None, "portfolio_url"),
    (("cover_letter", "cover letter", "coverletter", "求职信"), None, "cover_letter"),
    (("name",), None, "full_name"),
]

SUCCESS_HINTS = ("thank you", "application submitted", "application received", "successfully", "已提交", "提交成功")


@register_adapter
class GenericApplyAdapter:
    name = "generic"

    def apply(self, ctx: ApplyContext) -> ApplyResult:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            return ApplyResult(False, error_code="playwright_missing", error_detail=str(exc))

        p = ctx.payload
        shots: list[str] = []

        with sync_playwright() as pw:
            browser, page_ctx = new_stealth_context(pw)
            page = page_ctx.new_page()
            try:
                page.goto(ctx.posting["apply_url"], wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(3500)
                # Workday 等多步表單：先嘗試點擊 Apply 按鈕
                for text in ("Apply", "Apply Now", "申请", "立即申请"):
                    try:
                        btn = page.locator(f"button:has-text('{text}'), a:has-text('{text}')").first
                        if btn.count() and btn.is_visible():
                            btn.click()
                            page.wait_for_load_state("domcontentloaded")
                            page.wait_for_timeout(3000)
                            break
                    except Exception:  # noqa: BLE001
                        continue

                if detect_captcha(page):
                    shot = take_screenshot(page, "captcha.png", _shot_dir(ctx.user_id))
                    if shot:
                        shots.append(shot)
                    browser.close()
                    return ApplyResult(
                        False, error_code="captcha",
                        manual=ManualRequest("captcha", "申請頁出現人機驗證，請處理後點擊「已處理」",
                                             {"confirm": {"label": "我已處理驗證碼", "type": "checkbox"}}, shot),
                        screenshots=shots,
                    )

                inputs = _collect_inputs(page)
                unfilled_required: list[str] = []
                for inp in inputs:
                    if inp["type"] == "file":
                        continue
                    value, matched = _value_for(inp, p, ctx)
                    if value and inp["editable"]:
                        try:
                            page.locator(inp["selector"]).first.fill(value)
                        except Exception:  # noqa: BLE001
                            pass
                    elif matched and inp["required"] and inp["editable"] and not value:
                        unfilled_required.append(inp["label"] or inp["name"] or inp["selector"])
                human_pause()

                if ctx.resume_local_path and any(i["type"] == "file" for i in inputs):
                    upload_file(page, ["input[type=file]"], ctx.resume_local_path)
                    human_pause(1.0, 2.5)

                shot = take_screenshot(page, "before_submit.png", _shot_dir(ctx.user_id))
                if shot:
                    shots.append(shot)

                if unfilled_required:
                    browser.close()
                    return ApplyResult(
                        False, error_code="missing_field",
                        error_detail="必填字段缺數據: " + ", ".join(unfilled_required[:6]),
                        manual=ManualRequest(
                            "missing_field",
                            "申請表有必填字段沒有對應數據，請補充（格式：每行「字段=值」）",
                            {"values": {"label": f"待填字段: {', '.join(unfilled_required[:6])}",
                                        "type": "textarea"}},
                            shot,
                        ),
                        screenshots=shots,
                    )

                if ctx.dry_run:
                    browser.close()
                    return ApplyResult(True, external_ref="DRY_RUN", screenshots=shots)

                submitted = False
                for sel in ("button[type=submit]", "input[type=submit]",
                            "button:has-text('Submit')", "button:has-text('提交')"):
                    loc = page.locator(sel).first
                    if loc.count() and loc.is_visible():
                        loc.click()
                        page.wait_for_timeout(6000)
                        submitted = True
                        break
                content = (page.content() or "").lower()
                success = submitted and any(h in content for h in SUCCESS_HINTS)
                shot = take_screenshot(page, "after_submit.png", _shot_dir(ctx.user_id))
                if shot:
                    shots.append(shot)
                browser.close()
                if success:
                    return ApplyResult(True, external_ref=ctx.posting["external_id"], screenshots=shots)
                return ApplyResult(
                    False, error_code="submit_unconfirmed" if submitted else "no_submit_button",
                    error_detail="提交未確認成功，請人工確認",
                    manual=ManualRequest(
                        "confirm_content", "通用表單提交未確認成功，請查看截圖並補充說明",
                        {"note": {"label": "補充說明（可空）", "type": "text"},
                         "confirmed": {"label": "已確認提交成功", "type": "checkbox"}}, shot,
                    ),
                    screenshots=shots,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("通用投遞異常 app=%s", ctx.application_id)
                try:
                    browser.close()
                except Exception:  # noqa: BLE001
                    pass
                return ApplyResult(False, error_code="adapter_error",
                                   error_detail=str(exc)[:800], screenshots=shots)


def _collect_inputs(page) -> list[dict]:
    return page.evaluate(
        """
        () => Array.from(document.querySelectorAll(
          'input:not([type=hidden]), textarea, select'
        )).map((el, i) => {
          const label = el.labels && el.labels[0] ? el.labels[0].innerText.trim()
            : (el.closest('label') ? el.closest('label').innerText.trim() : '');
          const id = 'jobfly_field_' + i;
          if (!el.id) el.id = id;
          return {
            selector: '#' + el.id,
            type: (el.type || el.tagName.toLowerCase()),
            name: el.name || '',
            placeholder: el.placeholder || '',
            label: label,
            required: el.required || el.getAttribute('aria-required') === 'true',
            editable: !(el.readOnly || el.disabled),
            tag: el.tagName.toLowerCase(),
          };
        })
        """
    )


def _value_for(inp: dict, payload: dict, ctx: ApplyContext) -> tuple[str, bool]:
    hay = f"{inp['name']} {inp['placeholder']} {inp['label']}".lower()
    for keywords, _, field in FIELD_MAP:
        if any(k in hay for k in keywords):
            if field == "first_name":
                return _split_name(payload.get("full_name") or "")[0], True
            if field == "last_name":
                return _split_name(payload.get("full_name") or "")[1], True
            if field == "cover_letter":
                return ctx.cover_letter or "", True
            if field in ("linkedin_url", "portfolio_url"):
                v = payload.get(field)
                return v or "", bool(v)
            v = payload.get(field)
            if isinstance(v, (dict, list)):
                v = ""
            return str(v or ""), True
    return "", False


def _split_name(full: str) -> tuple[str, str]:
    parts = (full or "Candidate").strip().split()
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    return parts[0] if parts else "Candidate", "."


def _shot_dir(user_id: str) -> str:
    import os
    import tempfile

    d = os.path.join(tempfile.gettempdir(), "jobfly-shots", user_id)
    os.makedirs(d, exist_ok=True)
    return d
