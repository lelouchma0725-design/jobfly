"""中信證券招聘系統適配器（careers.citics.com）。

站點分析（2026-10 實測，Playwright 抓包）：
- API 網關：https://global-kong.citics.com（Kong）
- 列表：POST /api/v1/recruit/getPositionList
  body: sysNo=CSE001&recruitType=08&deptype=Branch&positionName=&pageSize=20&pageNo=1
  recruitType=08 為分支機構校園招聘（2027 屆）；deptype: Branch/Headquarters
- 響應：{errorCode:0, count, positionList:[{positionNo, positionName, deptName,
  companyName, workplace, reqendDate}]}
- 詳情：POST /api/v1/recruit/getPositionInfo（需 positionNo）
"""
from __future__ import annotations

import logging

import httpx

from app.collectors.base import JobPosting, register

logger = logging.getLogger(__name__)

BASE = "https://careers.citics.com"
GATEWAY = "https://global-kong.citics.com"
COMPANY_NAME = "中信證券"

# (recruitType, deptype, 標籤) —— 08 分支校招已實測；其餘類型值在頁面路由可擴展
TABS = (
    ("08", "Branch", "校園招聘(分支)"),
    ("08", "Headquarters", "校園招聘(總部)"),
)


def _fetch_tab(recruit_type: str, deptype: str, page: int) -> list[dict]:
    resp = httpx.post(
        f"{GATEWAY}/api/v1/recruit/getPositionList",
        data={
            "sysNo": "CSE001",
            "recruitType": recruit_type,
            "deptype": deptype,
            "positionName": "",
            "pageSize": "20",
            "pageNo": str(page),
        },
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errorCode") not in (0, "0", None):
        raise RuntimeError(f"中信接口錯誤: {data.get('errorMsg')}")
    return data.get("positionList") or []


@register
class CiticsCollector:
    name = "citics"

    def collect(self, target: dict) -> list[JobPosting]:
        postings: list[JobPosting] = []
        seen: set[str] = set()
        for recruit_type, deptype, tab_name in TABS:
            for page in range(1, 10):
                try:
                    jobs = _fetch_tab(recruit_type, deptype, page)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("citics 採集失敗 type=%s dept=%s p=%s: %s",
                                   recruit_type, deptype, page, exc)
                    break
                if not jobs:
                    break
                for j in jobs:
                    key = f"{recruit_type}:{j['positionNo']}"
                    if key in seen:
                        continue
                    seen.add(key)
                    postings.append(JobPosting(
                        source="citics",
                        external_id=str(j["positionNo"]),
                        company_name=f"{COMPANY_NAME}·{j.get('companyName') or j.get('deptName') or ''}",
                        title=(j.get("positionName") or "").strip(),
                        apply_url=f"{BASE}/campus/branch",
                        location=(j.get("workplace") or "").strip() or None,
                        department=(j.get("deptName") or "").strip() or None,
                        description_text=(
                            f"部門：{j.get('deptName')}\n地點：{j.get('workplace')}\n"
                            f"申請截止：{j.get('reqendDate')}（{tab_name}）"
                        ),
                        posted_at=None,
                        raw={"recruit_type": recruit_type, "tab": tab_name, **j},
                    ))
        return postings
