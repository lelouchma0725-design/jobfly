"""國聘平台（iguopin.com）採集器。

接口（2026-10 抓包實測）：
- 列表：POST gp-api.iguopin.com/api/jobs/v1/recom-job
  body: {"search":{"page":1,"page_size":50,"district":["000000.110000",...]},
         "recom":{"update_time":true,"company_nature":true,"hot_job":true}}
- district 編碼：110000=北京、310000=上海、810000=香港
- 響應 data.list[]：job_id/job_name/company_name/recruitment_type_cn/
  min_wage/max_wage/wage_unit_cn/is_negotiable/district_list/contents 等

篩選策略（用戶要求）：
- 只採北京/上海/香港
- 薪資：非面議 且 max_wage >= 15000（元/月）
- 優先校園招聘；社會招聘暫緩（SOCIAL_ENABLED=False 時跳過）
"""
from __future__ import annotations

import logging

import httpx

from app.collectors.base import JobPosting, register

logger = logging.getLogger(__name__)

BASE = "https://gp-api.iguopin.com"
SITE = "https://www.iguopin.com"
COMPANY = "國聘"

DISTRICTS = ["000000.110000", "000000.310000", "000000.810000"]  # 北京/上海/香港
SOCIAL_ENABLED = False  # 暫緩社會招聘（用戶要求：先校園）
MIN_WAGE = 15000  # 元/月

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def _district_text(d: list | None) -> str:
    if not d:
        return ""
    parts = []
    for x in d:
        if isinstance(x, dict):
            parts.append(str(x.get("name") or x.get("district_name") or ""))
        else:
            parts.append(str(x))
    return "、".join(p for p in parts if p)


@register
class IguopinCollector:
    name = "iguopin"

    def collect(self, target: dict) -> list[JobPosting]:
        postings: list[JobPosting] = []
        seen: set[str] = set()
        client = httpx.Client(headers=HEADERS, timeout=30)
        try:
            for page in range(1, 51):
                try:
                    resp = client.post(
                        f"{BASE}/api/jobs/v1/recom-job",
                        json={"search": {"page": page, "page_size": 20,
                                         "district": DISTRICTS,
                                         "min_wage": MIN_WAGE,
                                         "recruitment_type": ["1161T1j6"]},
                              "recom": {"update_time": True,
                                        "company_nature": True,
                                        "hot_job": True}},
                    )
                    resp.raise_for_status()
                    data = resp.json().get("data") or {}
                    items = data.get("list") or []
                except Exception as exc:  # noqa: BLE001
                    logger.warning("iguopin 採集失敗 p=%s: %s", page, exc)
                    break
                if not items:
                    break
                for it in items:
                    key = str(it.get("job_id") or "")
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    rec_cn = str(it.get("recruitment_type_cn") or "")
                    is_campus = "校" in rec_cn
                    if not is_campus and not SOCIAL_ENABLED:
                        continue  # 社會招聘暫緩
                    # 薪資過濾：面議排除；max_wage >= 15K
                    try:
                        min_w = float(it.get("min_wage") or 0)
                        max_w = float(it.get("max_wage") or 0)
                    except (TypeError, ValueError):
                        min_w = max_w = 0.0
                    negotiable = bool(it.get("is_negotiable"))
                    if negotiable or max_w < MIN_WAGE:
                        continue
                    loc = _district_text(it.get("district_list"))
                    desc = str(it.get("contents") or "")[:6000]
                    postings.append(JobPosting(
                        source="iguopin",
                        external_id=key,
                        company_name=str(it.get("company_name") or COMPANY),
                        title=str(it.get("job_name") or "").strip(),
                        apply_url=f"{SITE}/job/detail?id={key}",
                        location=loc or None,
                        department=str(it.get("department_cn") or "") or None,
                        description_text=desc,
                        posted_at=str(it.get("start_time") or "") or None,
                        raw={
                            "tab": rec_cn,
                            "is_campus": is_campus,
                            "is_intern": "實習" in str(it.get("job_name") or ""),
                            "min_wage": min_w, "max_wage": max_w,
                            "wage_unit": it.get("wage_unit_cn"),
                            "education": it.get("education_cn"),
                            "experience": it.get("experience_cn"),
                            **it,
                        },
                    ))
                if len(items) < 20:
                    break
        finally:
            client.close()
        return postings
