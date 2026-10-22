"""博时基金（北森 hotjob 門戶）採集適配器。

接口（2026-10 Playwright 抓包實測）：
- 列表：POST {base}/wecruit/positionInfo/listPosition/{suiteKey}?iSaJAx=isAjax&request_locale=zh_CN&t={ms}
  form: isFrompb=true&recruitType={t}&pageSize=50&currentPage={n}
- recruitType：1=校園招聘、2=社會招聘、12=實習生招聘
- 響應：data.pageForm.{totalPage, positonNum, pageData:[{postName, department,
  company, postTypeName, publishDate, endDate, externalKey, recruitType}]}
- WAF：需完整瀏覽器頭 + Referer
"""
from __future__ import annotations

import logging
import time as _time

import httpx

from app.collectors.base import JobPosting, register

logger = logging.getLogger(__name__)

BASE = "https://bosera.hotjob.cn"
SUITE_KEY = "SU65f940241c240e0a2275bda8"
COMPANY = "博时基金"

TABS = (
    ("2", "社會招聘", False),
    ("1", "校園招聘", True),
    ("12", "實習生招聘", False),
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": f"{BASE}/{SUITE_KEY}/pb/social.html",
    "X-Requested-With": "XMLHttpRequest",
}


def _fetch(recruit_type: str, page: int) -> tuple[list[dict], int]:
    resp = httpx.post(
        f"{BASE}/wecruit/positionInfo/listPosition/{SUITE_KEY}"
        f"?iSaJAx=isAjax&request_locale=zh_CN&t={int(_time.time() * 1000)}",
        data={
            "isFrompb": "true",
            "recruitType": recruit_type,
            "pageSize": "50",
            "currentPage": str(page),
        },
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    form = (data.get("data") or {}).get("pageForm") or {}
    return form.get("pageData") or [], int(form.get("totalPage") or 0)


@register
class BoseraCollector:
    name = "bosera"

    def collect(self, target: dict) -> list[JobPosting]:
        postings: list[JobPosting] = []
        seen: set[str] = set()
        for recruit_type, tab_name, is_campus in TABS:
            for page in range(1, 21):
                try:
                    items, total_page = _fetch(recruit_type, page)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("bosera 採集失敗 type=%s p=%s: %s", recruit_type, page, exc)
                    break
                if not items:
                    break
                for it in items:
                    key = str(it.get("externalKey") or "")
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    title = str(it.get("postName") or "").strip()
                    postings.append(JobPosting(
                        source="bosera",
                        external_id=key,
                        company_name=COMPANY,
                        title=title,
                        apply_url=f"{BASE}/{SUITE_KEY}/pb/index.html",
                        location=None,
                        department=(it.get("department") or "").strip() or None,
                        description_text=(
                            f"【{tab_name}】{it.get('postTypeName') or ''}\n"
                            f"部門：{it.get('department') or ''}\n"
                            f"發布：{it.get('publishDate') or ''} 截止：{it.get('endDate') or ''}"
                        ),
                        posted_at=None,
                        raw={
                            "tab": tab_name,
                            "is_campus": is_campus,
                            "is_intern": recruit_type == "12",
                            "recruit_type": recruit_type,
                            **it,
                        },
                    ))
                if page >= total_page:
                    break
        return postings
