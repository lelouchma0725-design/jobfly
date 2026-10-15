"""Greenhouse 投遞適配器（Playwright）。

表單結構（boards.greenhouse.io 申請頁）：
- 基本信息：first_name / last_name / email / phone / location(city)
- 簡歷上傳：input[type=file]
- Cover Letter：textarea（可選）
- 自定義問題/EEO：出現時提交前檢測，擋住則轉人工
"""
from __future__ import annotations

import logging

from app.apply.base import ApplyContext, ApplyResult, ManualRequest, register_adapter
from app.apply.browser import (
    detect_captcha,
    human_pause,
    human_type,
    new_stealth_context,
    take_screenshot,
    try_fill,
    upload_file,
)

logger = logging.getLogger(__name__)

SUBMIT_SELECTORS = ["input[type=submit]", "button[type=submit]", "button:has-text('Submit Application')"]
SUCCESS_HINTS = ("thank you", "application submitted", "application received", "已提交", "提交成功")


@register_adapter
class GreenhouseApplyAdapter:
    name = "greenhouse"

    def apply(self, ctx: ApplyContext) -> ApplyResult:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            return ApplyResult(False, error_code="playwright_missing", error_detail=str(exc))

        p = ctx.payload
        first, last = _split_name(p.get("full_name") or "")
        shots: list[str] = []

        with sync_playwright() as pw:
            browser, page_ctx = new_stealth_context(pw)
            page = page_ctx.new_page()
            try:
                page.goto(ctx.posting["apply_url"], wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2500)
                # 申請入口按鈕
                try:
                    btn = page.locator("a:has-text('Apply'), button:has-text('Apply Now'), #apply_button").first
                    if btn.count() and btn.is_visible():
                        btn.click()
                        page.wait_for_load_state("domcontentloaded")
                        page.wait_for_timeout(2500)
                except Exception:  # noqa: BLE001
                    pass

                if detect_captcha(page):
                    shot = take_screenshot(page, "captcha.png", _shot_dir(ctx.user_id))
                    if shot:
                        shots.append(shot)
                    browser.close()
                    return ApplyResult(
                        False, error_code="captcha",
                        manual=ManualRequest(
                            "captcha", "Greenhouse 申請頁出現人機驗證，請處理後點擊「已處理」",
                            {"confirm": {"label": "我已處理驗證碼", "type": "checkbox"}},
                            shot,
                        ),
                        screenshots=shots,
                    )

                try_fill(page, ["#first_name", "input[name='job_application[first_name]']"], first)
                try_fill(page, ["#last_name", "input[name='job_application[last_name]']"], last)
                try_fill(page, ["#email", "input[name='job_application[email]']"], p.get("email") or "")
                try_fill(page, ["#phone", "input[name='job_application[phone]']"], p.get("phone") or "")
                try_fill(page, ["#candidate-location", "#job_application_location",
                                "input[data-qa='location-input']",
                                "input[autocomplete='address-level2']"], p.get("location") or "")
                human_pause()
                if ctx.resume_local_path:
                    upload_file(page, ["input#resume", "input[type=file]"], ctx.resume_local_path)
                    human_pause(1.0, 2.5)
                if ctx.cover_letter:
                    # 兩種形態：textarea（多數 board）或文件上傳（如 Cloudflare 的 board）
                    cl_ok = try_fill(page, ["textarea[name*='cover_letter']", "textarea#cover_letter"],
                                     ctx.cover_letter)
                    if not cl_ok:
                        cl_path = _temp_cover_letter(ctx.cover_letter)
                        if cl_path:
                            upload_file(page, ["input#cover_letter"], cl_path)

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
                if not submitted:
                    browser.close()
                    return ApplyResult(
                        False, error_code="no_submit_button", error_detail="未找到提交按鈕",
                        manual=ManualRequest("confirm_content", "找不到提交按鈕，請確認申請頁結構",
                                             screenshot_path=shot), screenshots=shots,
                    )
                content = (page.content() or "").lower()
                success = any(h in content for h in SUCCESS_HINTS)
                shot = take_screenshot(page, "after_submit.png", _shot_dir(ctx.user_id))
                if shot:
                    shots.append(shot)
                browser.close()
                if success:
                    return ApplyResult(True, external_ref=ctx.posting["external_id"], screenshots=shots)
                return ApplyResult(
                    False, error_code="submit_unconfirmed",
                    error_detail="提交後未檢測到成功提示，可能被表單校驗攔截",
                    manual=ManualRequest(
                        "confirm_content",
                        "Greenhouse 提交未確認成功，請查看截圖：若需補充內容請填寫，若已提交請確認",
                        {"note": {"label": "補充說明（可空）", "type": "text"},
                         "confirmed": {"label": "已確認提交成功", "type": "checkbox"}},
                        shot,
                    ),
                    screenshots=shots,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Greenhouse 投遞異常 app=%s", ctx.application_id)
                try:
                    browser.close()
                except Exception:  # noqa: BLE001
                    pass
                return ApplyResult(False, error_code="adapter_error",
                                   error_detail=str(exc)[:800], screenshots=shots)


def _split_name(full: str) -> tuple[str, str]:
    parts = (full or "Candidate").strip().split()
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    return parts[0] if parts else "Candidate", "."


def _temp_cover_letter(text: str) -> str | None:
    import os
    import tempfile

    try:
        fd, path = tempfile.mkstemp(suffix=".txt", prefix="jobfly_cl_")
        with os.fdopen(fd, "w") as f:
            f.write(text)
        return path
    except OSError:  # pragma: no cover
        return None


def _shot_dir(user_id: str) -> str:
    import os
    import tempfile

    d = os.path.join(tempfile.gettempdir(), "jobfly-shots", user_id)
    os.makedirs(d, exist_ok=True)
    return d
