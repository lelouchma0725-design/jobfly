"""飛書招聘門戶（jobs.feishu.cn）採集適配器 — 廣發基金 gffunds.jobs.feishu.cn。

接口（2026-10 Playwright 抓包實測）：
- 列表：POST {base}/api/v1/search/job/posts
  body: {"keyword":"","limit":50,"offset":0,...,"portal_type":6,
         "storefront_id_list":[],"portal_entrance":1}
- 響應：{code, data:{job_post_list:[...], count}}
- 門戶無崗位時 count=0 且 job_post_list 為空（合法狀態）
"""
from __future__ import annotations

import logging

import httpx

from app.collectors.base import JobPosting, register

logger = logging.getLogger(__name__)

# (門戶根, 公司名)
PORTALS = (
    ("https://gffunds.jobs.feishu.cn", "广发基金"),
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


@register
class FeishuCollector:
    name = "feishu"

    def collect(self, target: dict) -> list[JobPosting]:
        careers = str(target.get("careers_url") or "")
        portal = next((p for p in PORTALS if p[0] in careers), PORTALS[0])
        base, company = portal
        postings: list[JobPosting] = []
        seen: set[str] = set()
        for offset in range(0, 1000, 50):
            try:
                resp = httpx.post(
                    f"{base}/api/v1/search/job/posts",
                    headers=HEADERS,
                    json={
                        "keyword": "", "limit": 50, "offset": offset,
                        "job_category_id_list": [], "tag_id_list": [],
                        "location_code_list": [], "subject_id_list": [],
                        "recruitment_id_list": [], "portal_type": 6,
                        "job_function_id_list": [], "storefront_id_list": [],
                        "portal_entrance": 1,
                    },
                    timeout=25,
                )
                resp.raise_for_status()
                data = (resp.json().get("data") or {})
                items = data.get("job_post_list") or []
            except Exception as exc:  # noqa: BLE001
                logger.warning("feishu 採集失敗 off=%s: %s", offset, exc)
                break
            if not items:
                break
            for it in items:
                key = str(it.get("id") or "")
                if not key or key in seen:
                    continue
                seen.add(key)
                title = (it.get("title") or it.get("job_name") or "").strip()
                cities = it.get("city_info") or it.get("city_list") or []
                if isinstance(cities, list):
                    loc = "、".join(str(c.get("name")) for c in cities if isinstance(c, dict) and c.get("name"))
                else:
                    loc = str(it.get("city") or "") or None
                dept = it.get("department") or (it.get("department_info") or {}).get("name") if isinstance(it.get("department_info"), dict) else None
                desc = it.get("description") or it.get("job_requirement") or ""
                rec_type = str(it.get("recruit_type") or it.get("job_type") or "")
                postings.append(JobPosting(
                    source="feishu",
                    external_id=key,
                    company_name=company,
                    title=title,
                    apply_url=f"{base}/index/position/list",
                    location=loc,
                    department=str(dept) if dept else None,
                    description_text=str(desc)[:6000],
                    posted_at=None,
                    raw={
                        "tab": "校園招聘" if "校" in rec_type else "社會招聘",
                        "is_campus": "校" in rec_type,
                        "is_intern": "實習" in title or "实习" in title,
                        **it,
                    },
                ))
            if len(items) < 50:
                break
        return postings
