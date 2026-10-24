"""華泰柏瑞基金官網招聘專區採集器（www.huatai-pb.com/aboutUs/joinUs）。

靜態 HTML 表格分頁：index.html（第 1 頁）、index2.html（第 2 頁）。
表格列：序號 | 崗位名稱 | 工作城市 | 學歷要求 | 人數 | 操作
"""
from __future__ import annotations

import logging
import re

import httpx

from app.collectors.base import JobPosting, register

logger = logging.getLogger(__name__)

BASE = "https://www.huatai-pb.com/aboutUs/joinUs"
COMPANY = "华泰柏瑞基金"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def _rows(html: str) -> list[dict]:
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if not cells or not cells[0].isdigit():
            continue
        if len(cells) < 4:
            continue
        out.append({
            "title": cells[1],
            "location": cells[2],
            "education": cells[3] if len(cells) > 3 else "",
            "headcount": cells[4] if len(cells) > 4 else "",
        })
    return out


@register
class HuataiPBCollector:
    name = "huatai_pb"

    def collect(self, target: dict) -> list[JobPosting]:
        postings: list[JobPosting] = []
        seen: set[str] = set()
        for page_name in ("index.html", "index2.html"):
            try:
                resp = httpx.get(f"{BASE}/{page_name}", headers=HEADERS, timeout=25)
                resp.raise_for_status()
                rows = _rows(resp.text)
            except Exception as exc:  # noqa: BLE001
                logger.warning("huatai_pb 採集失敗 %s: %s", page_name, exc)
                break
            if not rows:
                break
            for it in rows:
                key = f"{page_name}:{it['title']}"
                if key in seen:
                    continue
                seen.add(key)
                postings.append(JobPosting(
                    source="huatai_pb",
                    external_id=key,
                    company_name=COMPANY,
                    title=it["title"],
                    apply_url=f"{BASE}/index.html",
                    location=it["location"] or None,
                    department=None,
                    description_text=(
                        f"華泰柏瑞基金官網招聘：{it['title']}\n"
                        f"工作城市：{it['location']}\n學歷要求：{it['education']}\n"
                        f"招聘人數：{it['headcount']}\n"
                        "（詳情見官網「邀您加入」，投遞郵箱 recruiter@huatai-pb.com）"
                    ),
                    posted_at=None,
                    raw={"page": page_name, **it},
                ))
        return postings
