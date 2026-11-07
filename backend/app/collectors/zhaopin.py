"""智聯招聘（zhaopin.com）採集器 — SSR 直出版本（無需瀏覽器，Render 可自動跑）。

- 列表：https://www.zhaopin.com/jobs/?jl={cityCode}&kw={keyword}&p={page}
  jl：530=北京、538=上海
- 卡片 SSR HTML 字段（2026-11 實測）：
  職位：<a href=".../jobdetail/CC{n}.htm" title="標題">
  薪資：<span class="job-card__salary">X</span>（未登錄時為 **-**元）
  公司：companydetail/CZ{n}.htm 鏈接 title
  地址：<span title="地址">
  標籤：job-card__skill-tag 文本
- 未登錄薪資一律「**-**元」——無法按薪資過濾，AI 匹配以貼合度為主。
"""
from __future__ import annotations

import logging
import re
from urllib.parse import quote

import httpx

from app.collectors.base import JobPosting, register

logger = logging.getLogger(__name__)

COMPANY = "智聯招聘"
KEYWORDS = ("数据分析", "量化研究", "金融科技", "行业研究", "商业分析")
CITIES = (("530", "北京"), ("538", "上海"))
PAGES_PER_KEYWORD = 3
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def _parse_cards(html: str) -> list[dict]:
    """按職位詳情鏈接切分卡片並解析字段。"""
    out = []
    for m in re.finditer(
        r'<a href="https://www\.zhaopin\.com/jobdetail/(CC\d+[A-Z0-9]*)\.htm" title="([^"]+)"',
        html,
    ):
        number, title = m.group(1), m.group(2)
        seg = html[m.start(): m.start() + 4000]
        salary = ""
        sm = re.search(r'job-card__salary">([^<]+)<', seg)
        if sm:
            salary = sm.group(1).strip()
        company = ""
        cm = re.search(r'companydetail/[^"]*\.htm" title="([^"]+)"', seg)
        if cm:
            company = cm.group(1).strip()
        addr = ""
        am = re.search(r'job-card__location[^>]*>.*?<span title="([^"]+)"', seg, re.S)
        if am:
            addr = am.group(1).strip()
        tags = [t.strip() for t in re.findall(r'job-card__skill-tag">\s*([^<]+?)\s*</span>', seg)]
        desc = ""
        dm = re.search(r'job-card__seo-description">\s*([^<]{20,400})', seg)
        if dm:
            desc = dm.group(1).strip()
        out.append({"external_id": number, "title": title, "salary": salary,
                    "company": company, "location": addr, "tags": tags, "desc": desc})
    return out


@register
class ZhaopinCollector:
    name = "zhaopin"

    def collect(self, target: dict) -> list[JobPosting]:
        postings: list[JobPosting] = []
        seen: set[str] = set()
        client = httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True)
        try:
            for kw in KEYWORDS:
                for jl, city_name in CITIES:
                    for pnum in range(1, PAGES_PER_KEYWORD + 1):
                        url = f"https://www.zhaopin.com/jobs/?jl={jl}&kw={quote(kw)}&p={pnum}"
                        try:
                            resp = client.get(url)
                            resp.raise_for_status()
                            cards = _parse_cards(resp.text)
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("zhaopin 採集失敗 kw=%s p=%s: %s", kw, pnum, exc)
                            break
                        if not cards:
                            break
                        for card in cards:
                            key = card["external_id"]
                            if key in seen:
                                continue
                            seen.add(key)
                            title = card["title"]
                            is_campus = "校" in title or "实习" in title
                            postings.append(JobPosting(
                                source="zhaopin",
                                external_id=key,
                                company_name=card["company"] or COMPANY,
                                title=title,
                                apply_url=f"https://www.zhaopin.com/jobdetail/{key}.htm",
                                location=card["location"] or city_name,
                                department=None,
                                description_text=card["desc"] or "、".join(card["tags"]) or title,
                                posted_at=None,
                                raw={
                                    "tab": "校園招聘" if is_campus else "社會招聘",
                                    "is_campus": is_campus,
                                    "is_intern": "实习" in title,
                                    "salary": card["salary"],
                                    "tags": card["tags"],
                                },
                            ))
        finally:
            client.close()
        return postings
