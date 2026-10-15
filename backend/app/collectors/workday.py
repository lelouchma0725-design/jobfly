"""Workday 適配器（JS 渲染 SPA，需 Playwright）。

Workday 招聘站 URL 形如：
  https://{company}.wd1.myworkdayjobs.com/{subdomain}?locations=...

實現：先用 httpx 直連其內部 cxs API（快路徑）；403/失敗時降級 Playwright
打開頁面並攔截 /wday/cxs/{tenant}/{subdomain}/jobs 響應（慢路徑）。
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

import httpx

from app.collectors.base import JobPosting, register

logger = logging.getLogger(__name__)

_HOST_RE = re.compile(r"^https?://([\w.-]+\.myworkdayjobs\.com)(?:/|$)", re.I)
_MAX_POSTINGS = 200


def _parse_tenant(url: str) -> tuple[str, str, str] | None:
    """返回 (base_origin, tenant, subdomain)。"""
    m = _HOST_RE.match(url)
    if not m:
        return None
    host = m.group(1)  # e.g. cloudflare.wd1.myworkdayjobs.com
    tenant = host.split(".")[0]
    path = urlparse(url).path.strip("/")
    parts = [p for p in path.split("/") if p and not p.startswith("?")]
    # 去掉語言前綴（如 en-US）
    if parts and re.match(r"^[a-z]{2}(-[A-Z]{2})?$", parts[0]):
        parts = parts[1:]
    subdomain = parts[0] if parts else tenant
    return f"https://{host}", tenant, subdomain


def _fetch_via_api(base: str, tenant: str, subdomain: str, timeout: float = 20.0) -> list[dict]:
    """快路徑：直連 Workday cxs API。"""
    body = {
        "appliedFacets": {},
        "limit": 20,
        "offset": 0,
        "searchText": "",
    }
    jobs: list[dict] = []
    for _ in range(10):  # 最多 10 頁 = 200 條
        resp = httpx.post(
            f"{base}/wday/cxs/{tenant}/{subdomain}/jobs",
            json=body,
            timeout=timeout,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": base,
                "Referer": f"{base}/{subdomain}",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("jobPostings") or []
        jobs.extend(batch)
        total = data.get("total") or 0
        if not batch or len(jobs) >= min(total, _MAX_POSTINGS):
            break
        body["offset"] = len(jobs)
    return jobs


def _fetch_via_playwright(url: str) -> list[dict]:
    """慢路徑：Playwright 打開頁面並攔截 cxs 響應。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Workday 採集需要 playwright：pip install -e '.[automation]'") from exc

    captured: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()

        def on_response(resp):
            if "/wday/cxs/" in resp.url and "/jobs" in resp.url and resp.status == 200:
                try:
                    data = resp.json()
                    captured.extend(data.get("jobPostings") or [])
                except Exception:  # noqa: BLE001
                    pass

        page.on("response", on_response)
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)  # 等首頁異步加載完成
        browser.close()
    return captured


def _to_postings(raw: list[dict], tenant: str) -> list[JobPosting]:
    postings: list[JobPosting] = []
    for j in raw:
        ext = str(j.get("bulletFields") or [])
        jid = j.get("externalPath") or str(j.get("jobSeqNo") or "")
        apply_url = f"https://{tenant}.wd1.myworkdayjobs.com{jid}" if jid.startswith("/") else jid
        postings.append(
            JobPosting(
                source="workday",
                external_id=str(j.get("jobSeqNo") or jid),
                company_name=j.get("companyName") or tenant,
                title=j.get("title") or "",
                apply_url=apply_url,
                location=(j.get("locationsText") or "").strip() or None,
                department=None,
                description_text=_jd_from_bullets(j),
                posted_at=str(j.get("postedOn") or "").split("T")[0] or None,
                raw=j,
            )
        )
    return postings


def _jd_from_bullets(j: dict) -> str | None:
    bullets = j.get("bulletFields") or []
    if not bullets:
        return None
    return "\n".join(
        f"- {b}" for b in bullets if isinstance(b, str) and b.strip()
    ) or None


@register
class WorkdayCollector:
    name = "workday"

    def collect(self, target: dict) -> list[JobPosting]:
        url = target.get("careers_url") or ""
        parsed = _parse_tenant(url)
        if not parsed:
            raise ValueError(f"不是合法的 Workday 招聘 URL: {url}")
        base, tenant, subdomain = parsed
        try:
            raw = _fetch_via_api(base, tenant, subdomain)
        except httpx.HTTPError as exc:
            logger.warning("Workday API 快路徑失敗(%s)，降級 Playwright", exc)
            raw = _fetch_via_playwright(url)
        return _to_postings(raw, tenant)
