"""中歐基金採集器（舊版北森 CmsPortal 門戶，zofund.zhiye.com）。

服務端渲染 HTML：
- 列表：/campus（校園）、/social（社招）、/intern（實習），分頁 ?PageIndex=N
- 表格：職位名 | 部門 | 體系 | 城市 | 日期 | 詳情 href=/campusxq?jobId=XXX
- 詳情：/campusxq?jobId=XXX（含工作職責/任職資格/類別/城市/薪酬）
"""
from __future__ import annotations

import logging
import re

import httpx

from app.collectors.base import JobPosting, register

logger = logging.getLogger(__name__)

BASE = "https://zofund.zhiye.com"
COMPANY = "中欧基金"
TABS = (
    ("/campus", "校園招聘", True),
    ("/social", "社會招聘", False),
    ("/intern", "實習生招聘", False),
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Encoding": "gzip, deflate",
}


def _clean(html: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@register
class ZofundCollector:
    name = "zofund"

    def collect(self, target: dict) -> list[JobPosting]:
        postings: list[JobPosting] = []
        seen: set[str] = set()
        client = httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True)
        try:
            for tab_path, tab_name, is_campus in TABS:
                for page in range(1, 11):
                    try:
                        resp = client.get(f"{BASE}{tab_path}?PageIndex={page}")
                        resp.raise_for_status()
                        html = resp.text
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("zofund 列表失敗 %s p=%s: %s", tab_path, page, exc)
                        break
                    rows = []
                    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
                        cells = [re.sub(r"<[^>]+>", " ", c).strip()
                                 for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
                        hrefs = re.findall(r'href="([^"]+)"', r)
                        if cells and hrefs:
                            job_id = next((h for h in hrefs if "jobId=" in h), None)
                            if job_id:
                                rows.append((cells, job_id))
                    if not rows:
                        break
                    for cells, job_href in rows:
                        job_id = re.search(r"jobId=(\d+)", job_href)
                        if not job_id:
                            continue
                        key = job_id.group(1)
                        if key in seen:
                            continue
                        seen.add(key)
                        title = cells[0] if cells else ""
                        dept = cells[1] if len(cells) > 1 else ""
                        city = cells[3] if len(cells) > 3 else ""
                        desc = ""
                        try:
                            d = client.get(f"{BASE}/campusxq?jobId={key}")
                            if d.status_code == 200:
                                text = _clean(d.text)
                                m = re.search(r"工作职责：\s*(.*?)任职资格：", text, re.S)
                                if m:
                                    desc = f"職責：{m.group(1).strip()}"
                                m2 = re.search(r"任职资格：\s*(.*?)(?:立即申请|返回列表)", text, re.S)
                                if m2:
                                    desc = f"{desc}\n資格：{m2.group(1).strip()}"
                        except Exception:  # noqa: BLE001
                            pass
                        postings.append(JobPosting(
                            source="zofund",
                            external_id=key,
                            company_name=COMPANY,
                            title=title,
                            apply_url=f"{BASE}/campusxq?jobId={key}",
                            location=city or None,
                            department=dept or None,
                            description_text=desc[:6000],
                            posted_at=None,
                            raw={"tab": tab_name, "is_campus": is_campus,
                                 "is_intern": tab_name == "實習生招聘"},
                        ))
                    if page == 1 and len(rows) < 10:
                        break
        finally:
            client.close()
        return postings
