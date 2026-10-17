"""中信證券招聘系統適配器（careers.citics.com）。

站點分析（2026-10 實測，Playwright 抓包）：
- API 網關：https://global-kong.citics.com（Kong）
- 列表：POST /api/v1/recruit/getPositionList
  body: sysNo=CSE001&recruitType=08&deptype=Branch|Headquarter&batchId=63&practice=0&pageSize=100&pageNo=N
- recruitType：08=校園招聘（batchId=63 為 2027 屆批次）、05=社會招聘
- 全量 = 分支校招 40 + 總部校招 15 + 分支社招 221 + 總部社招 3
- 響應：{errorCode:0, count, positionList:[{positionNo, positionName, deptName,
  companyName, workplace, reqendDate, positionDesc, qualification}]}
"""
from __future__ import annotations

import logging

import httpx

from app.collectors.base import JobPosting, register

logger = logging.getLogger(__name__)

BASE = "https://careers.citics.com"
GATEWAY = "https://global-kong.citics.com"
COMPANY_NAME = "中信證券"

# (recruitType, deptype, 標籤, 額外參數)
TABS = (
    ("08", "Branch", "校園招聘·分支機構", {"batchId": "63", "practice": "0"}),
    ("08", "Headquarter", "校園招聘·總部", {"batchId": "63", "practice": "0"}),
    ("05", "Headquarter", "社會招聘·總部", {}),
    ("05", "Branch", "社會招聘·分支機構", {}),
)

PAGE_SIZE = 100


def _fetch_tab(recruit_type: str, deptype: str, extra: dict, page: int) -> list[dict]:
    resp = httpx.post(
        f"{GATEWAY}/api/v1/recruit/getPositionList",
        data={
            "sysNo": "CSE001",
            "recruitType": recruit_type,
            "deptype": deptype,
            "positionName": "",
            "pageSize": str(PAGE_SIZE),
            "pageNo": str(page),
            **extra,
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
        for recruit_type, deptype, tab_name, extra in TABS:
            for page in range(1, 6):  # 每 tab 最多 5 頁 × 100
                try:
                    jobs = _fetch_tab(recruit_type, deptype, extra, page)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("citics 採集失敗 type=%s dept=%s p=%s: %s",
                                   recruit_type, deptype, page, exc)
                    break
                if not jobs:
                    break
                for jb in jobs:
                    key = f"{recruit_type}:{jb['positionNo']}"
                    if key in seen:
                        continue
                    seen.add(key)
                    desc = (jb.get("positionDesc") or "").strip()
                    qual = (jb.get("qualification") or "").strip()
                    # 崗位方向：描述中的「岗位分为N个方向：A、B、C」解析為列表
                    import re as _re

                    directions: list[str] = []
                    m = _re.search(r"岗位分为\s*\d+\s*个方向[：:]\s*(.+)", desc)
                    if m:
                        directions = [d.strip() for d in _re.split(r"[、;；,，]", m.group(1)) if d.strip()]
                    postings.append(JobPosting(
                        source="citics",
                        external_id=key,
                        company_name=COMPANY_NAME,
                        title=(jb.get("positionName") or "").strip(),
                        apply_url=f"{BASE}/campus/branch",
                        location=(jb.get("workplace") or "").strip() or None,
                        department=(jb.get("deptName") or "").strip() or None,
                        description_text=(
                            f"【{tab_name}】{jb.get('deptdescrip') or ''}\n"
                            f"職責：{desc[:1500]}\n資格：{qual[:800]}"
                        ),
                        posted_at=None,
                        raw={
                            "recruit_type": recruit_type,
                            "tab": tab_name,
                            "is_campus": recruit_type == "08",
                            "batch_id": extra.get("batchId"),
                            "directions": directions,
                            **jb,
                        },
                    ))
                if len(jobs) < PAGE_SIZE:
                    break
        return postings
