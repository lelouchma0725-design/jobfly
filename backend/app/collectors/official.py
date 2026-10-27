"""官網採集路由：按 URL 特徵自動分發到正確的 ATS 適配器；無法識別時用通用啟發式。

識別規則：
- boards.greenhouse.io / greenhouse.io → Greenhouse
- jobs.lever.co / lever.co        → Lever
- *.myworkdayjobs.com             → Workday
- 其他 careers_url                → Generic（Playwright 啟發式，最佳努力）
"""
from __future__ import annotations

import logging

from app.collectors.base import JobPosting, get_collector, register

logger = logging.getLogger(__name__)

_ATS_HINTS = (
    ("greenhouse", ("greenhouse.io",)),
    ("lever", ("lever.co",)),
    ("workday", ("myworkdayjobs.com",)),
    ("gtht", ("hr.gtht.com",)),
    ("citics", ("careers.citics.com",)),
    ("beisen", ("zhiye.com",)),
    ("bosera", ("hotjob.cn", "wecruit.hotjob.cn")),
    ("huatai_pb", ("huatai-pb.com",)),
    ("feishu", ("jobs.feishu.cn",)),
)

GENERIC_LINK_LIMIT = 10  # 通用採集每站最多抓取詳情數


def detect_platform(careers_url: str) -> str:
    url = careers_url.lower()
    for platform, hints in _ATS_HINTS:
        if any(h in url for h in hints):
            return platform
    return "official"


@register
class OfficialCollector:
    """按 URL 分發；'official' 落到通用啟發式。"""

    name = "official"

    def collect(self, target: dict) -> list[JobPosting]:
        url = target.get("careers_url") or ""
        platform = detect_platform(url)
        if platform != "official":
            return get_collector(platform).collect(target)
        return _generic_collect(target)


def _generic_collect(target: dict) -> list[JobPosting]:
    """通用啟發式：Playwright 打開招聘頁，收集疑似崗位鏈接並抓取標題。

    只做鏈接+標題級採集（JD 詳情留待投遞階段處理），防止請求爆炸。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("通用官網採集需要 playwright：pip install -e '.[automation]'") from exc

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
