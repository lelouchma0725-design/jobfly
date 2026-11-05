"""通用官網採集器（精簡版唯一的採集適配器）。

策略：給定公司的招聘官網 careers_url，用瀏覽器打開頁面，
按鏈接文字/URL 的招聘關鍵詞啟發式地收集「崗位標題 + 申請鏈接」。
只做鏈接與標題級採集（JD 詳情留待投遞階段處理），防止請求爆炸。

不再按 ATS 域名分發到定制適配器：新增公司只需在「關注公司」填寫官網地址即可。
"""
from __future__ import annotations

import logging

from app.collectors.base import JobPosting, register

logger = logging.getLogger(__name__)

GENERIC_LINK_LIMIT = 10  # 每站最多抓取詳情數


@register
class OfficialCollector:
    """通用官網採集（瀏覽器啟發式，最佳努力）。"""

    name = "official"

    def collect(self, target: dict) -> list[JobPosting]:
        return _generic_collect(target)


def _generic_collect(target: dict) -> list[JobPosting]:
    """用 Playwright 打開招聘頁，收集疑似崗位鏈接並抓取標題。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("官網採集需要 playwright：pip install -e '.[automation]'") from exc

    url = target.get("careers_url") or ""
    company = target.get("company_name") or url
    results: list[JobPosting] = []
    job_hint = ("job", "career", "position", "opening", "vacanc", "招聘", "职位")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:  # noqa: BLE001
            browser.close()
            raise RuntimeError(f"官網打不開: {url} ({exc})") from exc
        page.wait_for_timeout(2500)
        links = page.eval_on_selector_all(
            "a",
            """els => els.map(e => ({
                   href: e.href || '',
                   text: (e.innerText || e.getAttribute('aria-label') || '').trim()
                 }))
                 .filter(l => l.href && l.text && l.text.length < 120)""",
        )
        seen: set[str] = set()
        for link in links:
            low_href = link["href"].lower()
            low_text = link["text"].lower()
            if not any(h in low_href or h in low_text for h in job_hint):
                continue
            key = link["href"].split("?")[0]
            if key in seen:
                continue
            seen.add(key)
            results.append(
                JobPosting(
                    source="official",
                    external_id=key,
                    company_name=company,
                    title=link["text"],
                    apply_url=link["href"],
                )
            )
            if len(results) >= GENERIC_LINK_LIMIT:
                break
        browser.close()
    if not results:
        logger.warning("官網通用採集未發現崗位鏈接: %s", url)
    return results
