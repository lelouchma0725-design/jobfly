"""Playwright 瀏覽器工具：反檢測啟動、擬人輸入、上傳、截圖、驗證碼檢測。"""
from __future__ import annotations

import logging
import os
import random
import time

logger = logging.getLogger(__name__)

_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
window.chrome = window.chrome || { runtime: {} };
"""

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

CAPTCHA_HINTS = ("recaptcha", "hcaptcha", "arkose", "captcha", "verify you are human", "人机验证", "安全验证")

# 隱形 reCAPTCHA 的腳本/隱藏 iframe 不應觸發人工接管；只認「可見的挑戰」
VISIBLE_CAPTCHA_TEXT = ("人机验证", "安全验证", "verify you are human", "prove you are human", "请完成验证")


def new_stealth_context(pw):
    browser = pw.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    ctx = browser.new_context(
        user_agent=UA,
        locale="en-US",
        timezone_id="America/New_York",
        viewport={"width": 1440, "height": 960},
    )
    ctx.add_init_script(_STEALTH_JS)
    return browser, ctx


def human_type(page, selector: str, text: str, delay_ms: tuple[int, int] = (40, 120)) -> None:
    """逐字輸入，模擬人類打字節奏。"""
    if not text:
        return
    page.fill(selector, "")
    page.click(selector)
    for ch in text:
        page.keyboard.type(ch, delay=random.randint(*delay_ms))


def try_fill(page, selectors: list[str], value: str) -> bool:
    """按候選選擇器順序嘗試填充，成功返回 True。"""
    if not value:
        return False
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() == 0 or not loc.is_visible():
                continue
            loc.fill(value)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


def upload_file(page, selectors: list[str], path: str) -> bool:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                loc.set_input_files(path)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def detect_captcha(page) -> bool:
    """只檢測用戶真正需要處理的可見驗證碼，避免隱形 reCAPTCHA 誤報。"""
    try:
        for hint in ("recaptcha", "hcaptcha", "arkose", "funcaptcha"):
            loc = page.locator(f'iframe[src*="{hint}"]')
            for i in range(loc.count()):
                try:
                    el = loc.nth(i)
                    box = el.bounding_box()
                    # 徽章（~76x76）不需用戶操作；挑戰窗口高≥200 或 寬≥400 才需要人工
                    if el.is_visible() and box and (box["height"] >= 200 or box["width"] >= 400):
                        return True
                except Exception:  # noqa: BLE001
                    continue
        for text in VISIBLE_CAPTCHA_TEXT:
            loc = page.get_by_text(text)
            try:
                if loc.count() and loc.first.is_visible():
                    return True
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        return False
    return False


def take_screenshot(page, name: str, out_dir: str) -> str | None:
    try:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, name)
        page.screenshot(path=path, full_page=False)
        return path
    except Exception as exc:  # noqa: BLE001
        logger.warning("截圖失敗: %s", exc)
        return None


def human_pause(min_s: float = 0.6, max_s: float = 2.2) -> None:
    time.sleep(random.uniform(min_s, max_s))
