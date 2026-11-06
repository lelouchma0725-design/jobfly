"""智聯招聘（zhaopin.com）採集器。

SSR 直出（無列表 API）：職位卡片在 HTML 中。
- 列表：https://www.zhaopin.com/jobs/?jl={cityCode}&kw={keyword}&p={page}
  jl：530=北京、538=上海
- 卡片 DOM：div.job-card → [aria-label]=標題、.job-card__salary=薪資、
  .job-card__company-name=公司、.job-card__address=城市、.job-card__skill-tag=標籤
- 限制：未登錄狀態薪資一律顯示「**-**元」——無法按薪資過濾，
  採集按「高薪」排序（智聯把高薪崗位排前面），AI 匹配以貼合度為主。
- 職位編號（CC...）按卡片順序對應頁面中的 CC 號碼序列。
"""
from __future__ import annotations

import logging
import re
from urllib.parse import quote

from app.collectors.base import JobPosting, register

logger = logging.getLogger(__name__)

COMPANY = "智聯招聘"
KEYWORDS = ("数据分析", "量化研究", "金融科技", "行业研究", "商业分析")
CITIES = (("530", "北京"), ("538", "上海"))
PAGES_PER_KEYWORD = 3  # 高薪排序前 3 頁（每頁 20）


@register
class ZhaopinCollector:
    name = "zhaopin"

    def collect(self, target: dict) -> list[JobPosting]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:  # pragma: no cover
            logger.warning("zhaopin 需要 Playwright")
            return []

        postings: list[JobPosting] = []
        seen: set[str] = set()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 Chrome/126 Safari/537.36", locale="zh-CN")
            page = ctx.new_page()
            try:
                for kw in KEYWORDS:
                    for jl, city_name in CITIES:
                        for pnum in range(1, PAGES_PER_KEYWORD + 1):
                            url = (f"https://www.zhaopin.com/jobs/?jl={jl}"
                                   f"&kw={quote(kw)}&p={pnum}")
                            try:
                                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                                page.wait_for_timeout(10000)
                            except Exception as exc:  # noqa: BLE001
                                logger.warning("zhaopin 導航失敗 kw=%s p=%s: %s", kw, pnum, exc)
                                break
                            try:
                                cards = page.eval_on_selector_all(
                                    "div.job-card",
                                    """els => els.map(el => ({
                                        title: el.querySelector('[aria-label]')?.getAttribute('aria-label') || '',
                                        salary: el.querySelector('.job-card__salary')?.innerText || '',
                                        company: el.querySelector('.job-card__company-name')?.getAttribute('title')
                                                 || el.querySelector('.job-card__company')?.innerText || '',
                                        addr: el.querySelector('.job-card__address, .job-card__city, .job-card__location')?.innerText || '',
                                        tags: Array.from(el.querySelectorAll('.job-card__skill-tag')).map(t => t.innerText.trim()),
                                    }))""")
                                html = page.content()
                            except Exception as exc:  # noqa: BLE001
                                logger.warning("zhaopin 解析失敗 kw=%s p=%s: %s", kw, pnum, exc)
                                break
                            if not cards:
                                break
                            # CC 號碼按序對應卡片（頁面 qrcode 等請求順序一致）
                            cc_numbers = re.findall(r"CC\d{6,}[A-Z0-9]*", html)
                            cc_numbers = list(dict.fromkeys(cc_numbers))
                            for idx, card in enumerate(cards):
                                title = (card.get("title") or "").strip()
                                if not title:
                                    continue
                                number = cc_numbers[idx] if idx < len(cc_numbers) else ""
                                key = number or f"zp-{kw}-{jl}-{pnum}-{idx}"
                                if key in seen:
                                    continue
                                seen.add(key)
                                tags = card.get("tags") or []
                                is_campus = "校" in title or "实习" in title
                                postings.append(JobPosting(
                                    source="zhaopin",
                                    external_id=key,
                                    company_name=str(card.get("company") or COMPANY),
                                    title=title,
                                    apply_url=(f"https://www.zhaopin.com/jobdetail/{number}.htm"
                                               if number else "https://www.zhaopin.com/jobs/"),
                                    location=(card.get("addr") or city_name).strip(),
                                    department=None,
                                    description_text="、".join(tags) or title,
                                    posted_at=None,
                                    raw={
                                        "tab": "校園招聘" if is_campus else "社會招聘",
                                        "is_campus": is_campus,
                                        "is_intern": "实习" in title,
                                        "salary": card.get("salary"),
                                        "tags": tags,
                                        **card,
                                    },
                                ))
                            page.wait_for_timeout(1500)
            finally:
                browser.close()
        return postings
