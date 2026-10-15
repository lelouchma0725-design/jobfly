"""Lever 投遞適配器（Playwright）。

申請頁形如 jobs.lever.co/{site}/{id}/apply：
- name / email / phone / org / urls(LinkedIn等) / resume(file) / comments(cover letter)
"""
from __future__ import annotations

import logging

from app.apply.base import ApplyContext, ApplyResult, ManualRequest, register_adapter
from app.apply.browser import (
    detect_captcha,
    human_pause,
    new_stealth_context,
    take_screenshot,
    try_fill,
    upload_file,
)

logger = logging.getLogger(__name__)

SUBMIT_SELECTORS = ["button[type=submit]", "button:has-text('Submit Application')", "input[type=submit]"]
SUCCESS_HINTS = ("thank you", "application submitted", "application received", "已提交")


@register_adapter
class LeverApplyAdapter:
    name = "lever"

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
                page.wait_for_timeout(3000)

                if detect_captcha(page):
                    shot = take_screenshot(page, "captcha.png", _shot_dir(ctx.user_id))
                    if shot:
                        shots.append(shot)
                    browser.close()
                    return ApplyResult(
                        False, error_code="captcha",
                        manual=ManualRequest("captcha", "Lever 申請頁出現人機驗證，請處理後點擊「已處理」",
                                             {"confirm": {"label": "我已處理驗證碼", "type": "checkbox"}}, shot),
                        screenshots=shots,
                    )

                try_fill(page, ["input[name=name]"], p.get("full_name") or "")
                try_fill(page, ["input[name=email]", "input[type=email]"], p.get("email") or "")
                try_fill(page, ["input[name=phone]", "input[type=tel]"], p.get("phone") or "")
                try_fill(page, ["input[name=org]", "input[name=company]"], "")
                try_fill(page, ["input[placeholder*='linkedin' i]"], p.get("linkedin_url") or "")
                human_pause()
                if ctx.resume_local_path:
                    upload_file(page, ["input[type=file]"], ctx.resume_local_path)
                    human_pause(1.0, 2.5)
                if ctx.cover_letter:
                    try_fill(page, ["textarea[name=comments]"], ctx.cover_letter)

                shot = take_screenshot(page, "before_submit.png", _shot_dir(ctx.user_id))
                if shot:
                    shots.append(shot)

                if ctx.dry_run:
                    browser.close()
                    return ApplyResult(True, external_ref="DRY_RUN", screenshots=shots)

                submitted = False
                for sel in SUBMIT_SELECTORS:
                    loc = page.locator(sel).first
                    if loc.count() and loc.is_visible():
                        loc.click()
                        page.wait_for_timeout(5000)
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
                if not submitted:
                    return ApplyResult(
                        False, error_code="no_submit_button", error_detail="未找到提交按鈕",
                        manual=ManualRequest("confirm_content", "找不到提交按鈕，請確認申請頁結構",
                                             screenshot_path=shot), screenshots=shots,
                    )
                return ApplyResult(
                    False, error_code="submit_unconfirmed",
                    error_detail="提交後未檢測到成功提示",
                    manual=ManualRequest(
                        "confirm_content", "Lever 提交未確認成功，請查看截圖並補充說明",
                        {"note": {"label": "補充說明（可空）", "type": "text"},
                         "confirmed": {"label": "已確認提交成功", "type": "checkbox"}}, shot,
                    ),
                    screenshots=shots,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Lever 投遞異常 app=%s", ctx.application_id)
                try:
                    browser.close()
                except Exception:  # noqa: BLE001
                    pass
                return ApplyResult(False, error_code="adapter_error",
                                   error_detail=str(exc)[:800], screenshots=shots)


def _shot_dir(user_id: str) -> str:
    import os
    import tempfile

    d = os.path.join(tempfile.gettempdir(), "jobfly-shots", user_id)
    os.makedirs(d, exist_ok=True)
    return d
