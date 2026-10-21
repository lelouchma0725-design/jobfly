"""北森招聘雲（zhiye.com）採集適配器 — 中金公司 cicc.zhiye.com。

接口（2026-10 Playwright 抓包實測）：
- 列表：POST /api/Jobad/GetJobAdPageList
  body: {"Category":[1|2|3|4], "DisplayFields":[...], "PageIndex":0, "PageSize":50,
         "PortalId":"1bb97a43-1bb9-42c2-b5c6-19ddc82c0cb9"}
- Category：1=社會招聘、2=校園招聘（3/4=暑期/項目實習，不同門戶可能不同）
- 響應：{Count, Data:[{JobAdId, JobAdName, Org, Category, LocNames[], Salary,
  Duty, Require, PostDate, HeadCount}]}
"""
from __future__ import annotations

import logging

import httpx

from app.collectors.base import JobPosting, register

logger = logging.getLogger(__name__)

# (門戶根, portalId, 標籤, category)
PORTALS = (
    ("https://cicc.zhiye.com", "1bb97a43-1bb9-42c2-b5c6-19ddc82c0cb9", "中金公司", "cicc"),
)

CATEGORIES = (
    (1, "社會招聘"),
    (2, "校園招聘"),
    (3, "暑期實習"),
    (4, "項目實習"),
)

DISPLAY_FIELDS = ["Category", "Kind", "LocId", "Org", "HeadCount", "Station",
                  "EndTime", "PostDate", "Salary", "ClassificationOne", "ClassificationTwo"]

COMPANY = "中金公司"


@register
class BeisenCollector:
    name = "beisen"

    def collect(self, target: dict) -> list[JobPosting]:
        base, portal_id, _, _ = PORTALS[0]
        postings: list[JobPosting] = []
        seen: set[str] = set()
        for cat, tab_name in CATEGORIES:
            page = 0
            while page < 20:  # 每頁 50，最多 1000
                try:
                    resp = httpx.post(
                        f"{base}/api/Jobad/GetJobAdPageList",
                        json={
                            "Category": [cat],
                            "DisplayFields": DISPLAY_FIELDS,
                            "PageIndex": page,
                            "PageSize": 50,
                            "PortalId": portal_id,
                        },
                        headers={
                            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                          "AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                        },
                        timeout=30,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    items = data.get("Data") or []
                except Exception as exc:  # noqa: BLE001
                    logger.warning("beisen 採集失敗 cat=%s p=%s: %s", cat, page, exc)
                    break
                if not items:
                    break
                for it in items:
                    key = str(it.get("JobAdId") or it.get("Id") or "")
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    org = str(it.get("Org") or "")
                    desc = (
                        f"職責：{it.get('Duty') or ''}\n要求：{it.get('Require') or ''}"
                    )[:6000]
                    postings.append(JobPosting(
                        source="beisen",
                        external_id=key,
                        company_name=COMPANY,
                        title=str(it.get("JobAdName") or "").strip(),
                        apply_url=f"{base}/custom/social",
                        location="、".join(it.get("LocNames") or []) or None,
                        department=org or None,
                        description_text=desc,
                        posted_at=None,
                        raw={
                            "tab": tab_name,
                            "is_campus": cat == 2,
                            "category": cat,
                            "org": org,
                            "salary": it.get("Salary"),
                            **it,
                        },
                    ))
                if len(items) < 50:
                    break
                page += 1
        return postings
