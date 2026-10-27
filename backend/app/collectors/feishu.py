"""飛書招聘門戶（jobs.feishu.cn）採集適配器 — 廣發基金 gffunds.jobs.feishu.cn。

接口（2026-10 Playwright 抓包實測）：
- 列表：POST {base}/api/v1/search/job/posts
  body: {"keyword":"","limit":50,"offset":0,...,"portal_type":6,
         "storefront_id_list":[],"portal_entrance":1}
- **關鍵**：服務器按 `website-path` 請求頭決定崗位範圍（子頁面如 /833056=校園招聘項目，
  /index/position/list=社會招聘）。缺該頭時首頁範圍 count=0。
- 響應：{code, data:{job_post_list:[...], count}}
"""
from __future__ import annotations

import logging
import re

import httpx

from app.collectors.base import JobPosting, register

logger = logging.getLogger(__name__)

# (門戶根, 公司名)
# (門戶根, 公司名, 已知子頁面路徑)
PORTALS = (
    ("https://gffunds.jobs.feishu.cn", "广发基金",
     ["833056", "index/position/list"]),
)

HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

POST_BODY = {
    "keyword": "", "limit": 50, "offset": 0,
    "job_category_id_list": [], "tag_id_list": [],
    "location_code_list": [], "subject_id_list": [],
    "recruitment_id_list": [], "portal_type": 6,
    "job_function_id_list": [], "storefront_id_list": [],
    "portal_entrance": 1,
}


def _discover_paths(client: httpx.Client, base: str) -> list[str]:
    """從門戶首頁發現子頁面路徑（招聘項目數字頁 + 標準列表頁）。"""
    paths = ["index/position/list"]
    try:
        resp = client.get(f"{base}/index", timeout=25)
        for m in re.findall(r'href="/(\d+)"', resp.text):
            if m not in paths:
                paths.append(m)
    except Exception as exc:  # noqa: BLE001
        logger.warning("feishu 首頁路徑發現失敗: %s", exc)
    return paths


def _fetch_path(client: httpx.Client, base: str, path: str) -> list[dict]:
    body = dict(POST_BODY)
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "website-path": path,
        "portal-channel": "saas-career",
        "portal-platform": "pc",
        "Referer": f"{base}/{path}",
    }
    try:
        resp = client.post(f"{base}/api/v1/search/job/posts", headers=headers,
                           json=body, timeout=25)
        resp.raise_for_status()
        data = resp.json().get("data") or {}
        return data.get("job_post_list") or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("feishu 列表失敗 path=%s: %s", path, exc)
        return []


@register
class FeishuCollector:
    name = "feishu"

    def collect(self, target: dict) -> list[JobPosting]:
        careers = str(target.get("careers_url") or "")
        portal = next((p for p in PORTALS if p[0] in careers), PORTALS[0])
        base, company = portal[0], portal[1]
        known_paths = list(portal[2]) if len(portal) > 2 else []
        client = httpx.Client(headers=HEADERS_BASE, timeout=30, follow_redirects=True)
        postings: list[JobPosting] = []
        seen: set[str] = set()
        try:
            paths = list(known_paths)
            for p in _discover_paths(client, base):
                if p not in paths:
                    paths.append(p)
            for path in paths:
                items = _fetch_path(client, base, path)
                if not items:
                    continue
                for it in items:
                    key = str(it.get("id") or "")
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    title = (it.get("title") or "").strip()
                    cities = it.get("city_info") or it.get("city_list") or []
                    if isinstance(cities, list):
                        loc = "、".join(
                            str(c.get("name")) for c in cities
                            if isinstance(c, dict) and c.get("name")
                        ) or None
                    else:
                        loc = str(it.get("city") or "") or None
                    dept = it.get("department_id") or ""
                    desc = f"{it.get('description') or ''}\n要求：{it.get('requirement') or ''}"
                    rec_type = str(it.get("recruit_type") or "")
                    tab = str(it.get("job_subject") or "")
                    postings.append(JobPosting(
                        source="feishu",
                        external_id=key,
                        company_name=company,
                        title=title,
                        apply_url=f"{base}/{path}",
                        location=loc,
                        department=str(dept) if dept else None,
                        description_text=desc[:6000],
                        posted_at=str(it.get("publish_time") or "") or None,
                        raw={
                            "tab": tab or ("校園招聘" if "校" in rec_type else "社會招聘"),
                            "is_campus": "校" in rec_type or "校" in tab,
                            "is_intern": "實習" in title or "实习" in title or "實習" in tab,
                            "path": path,
                            **it,
                        },
                    ))
        finally:
            client.close()
        return postings
