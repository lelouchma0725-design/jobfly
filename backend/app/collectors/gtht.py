"""國泰海通證券招聘系統適配器（hr.gtht.com）。

站點分析（2026-10 實測）：
- 列表接口：向 tab 頁 URL POST {n:1, company[]:'', systemjobtype, p:頁碼}，返回 HTML 片段
  - recruit2 校園招聘 systemjobtype=2；society 社招 =1；recruit1 實習生 =3（未實測）
- 服務端 TLS 使用 legacy renegotiation，需 ssl.OP_LEGACY_SERVER_CONNECT
- 申請接口：POST /api/user/applyJob.json（需登錄 token + 系統內已建簡歷）
- 登錄有極驗驗證碼，自動化遇到時轉人工接管（見 app/apply/gtht_apply.py）
"""
from __future__ import annotations

import logging
import re
import ssl

import httpx

from app.collectors.base import JobPosting, register

logger = logging.getLogger(__name__)

BASE = "https://hr.gtht.com"
COMPANY_NAME = "國泰海通證券"

TABS = (
    ("recruit2", "校園招聘", "2"),
    ("society", "社會招聘", "1"),
    ("recruit1", "實習生招聘", "3"),
)

MAX_PAGES = 10
PAGE_SIZE = 30

_ID_RE = re.compile(r"data-job_id='(\d+)'")
# 每個 ul 塊：標題 / 部門 / 學歷 / 人數 / 地點 / 申請 / JD
_UL_RE = re.compile(r"<ul[^>]*>(.*?)</ul>", re.S)
_SPAN_RE = re.compile(r'<span title="([^"]*)"[^>]*class="con"')
_JD_RE = re.compile(r'class="job-description-li".*?<p>(.*?)</p>\s*</li>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _legacy_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
    return ctx


def _fetch_tab(tab: str, systemjobtype: str, page: int) -> list[dict]:
    resp = httpx.post(
        f"{BASE}/recruitment/main/{tab}",
        data={"n": "1", "company[]": "", "systemjobtype": systemjobtype, "p": str(page)},
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                               "AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36"},
        verify=_legacy_ssl_context(),
        timeout=30,
    )
    resp.raise_for_status()
    return _parse_fragment(resp.text)


def _parse_fragment(fragment: str) -> list[dict]:
    jobs: list[dict] = []
    for ul in _UL_RE.findall(fragment):
        job_id = _ID_RE.search(ul)
        if not job_id:
            continue
        spans = _SPAN_RE.findall(ul)
        jd_m = _JD_RE.search(ul)
        jd = _TAG_RE.sub("\n", jd_m.group(1)).strip() if jd_m else None
        if len(spans) >= 3:
            title, education, location = spans[0], spans[2], spans[4] if len(spans) > 4 else ""
        else:
            title, education, location = (spans[0] if spans else ""), "", ""
        jobs.append({
            "job_id": job_id.group(1),
            "title": title.strip(),
            "education": education.strip(),
            "location": location.strip(),
            "description": jd,
        })
    return jobs


@register
class GthtCollector:
    name = "gtht"

    def collect(self, target: dict) -> list[JobPosting]:
        postings: list[JobPosting] = []
        for tab, tab_name, systemjobtype in TABS:
            for page in range(1, MAX_PAGES + 1):
                try:
                    jobs = _fetch_tab(tab, systemjobtype, page)
                except httpx.HTTPError as exc:
                    logger.warning("gtht 採集失敗 tab=%s p=%s: %s", tab, page, exc)
                    break
                if not jobs:
                    break
                for j in jobs:
                    postings.append(JobPosting(
                        source="gtht",
                        external_id=j["job_id"],
                        company_name=COMPANY_NAME,
                        title=j["title"],
                        apply_url=f"{BASE}/recruitment/main/{tab}",
                        location=j["location"] or None,
                        description_text=j["description"],
                        posted_at=None,
                        raw={"education": j["education"], "tab": tab_name},
                    ))
                if len(jobs) < PAGE_SIZE:
                    break
        return postings
