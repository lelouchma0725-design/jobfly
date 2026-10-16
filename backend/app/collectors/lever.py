"""Lever 適配器（公開 Postings API，無需登錄，列表即含完整 JD）。

API: GET https://api.lever.co/v0/postings/{site}?mode=json
site 從 careers_url 解析：https://jobs.lever.co/palantir → palantir
"""
from __future__ import annotations

import re

import httpx

from app.collectors.base import JobPosting, register

_SITE_PATTERNS = (
    re.compile(r"jobs\.lever\.co/([\w-]+)(?:/|$|\?)"),
    re.compile(r"lever\.co/([\w-]+)(?:/|$|\?)"),
)


def _parse_site(careers_url: str) -> str | None:
    for pat in _SITE_PATTERNS:
        m = pat.search(careers_url)
        if m:
            return m.group(1)
    return None


@register
class LeverCollector:
    name = "lever"

    def collect(self, target: dict) -> list[JobPosting]:
        url = target.get("careers_url") or ""
        site = _parse_site(url)
        if not site:
            raise ValueError(f"無法從 URL 解析 Lever site: {url}")
        resp = httpx.get(
            f"https://api.lever.co/v0/postings/{site}?mode=json",
            timeout=20.0,
            headers={"User-Agent": "Mozilla/5.0 (JobsComing/0.1)"},
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            raise ValueError(f"Lever API 返回異常: {str(data)[:200]}")

        postings: list[JobPosting] = []
        for j in data:
            cats = j.get("categories") or {}
            postings.append(
                JobPosting(
                    source="lever",
                    external_id=str(j.get("id") or ""),
                    company_name=target.get("company_name") or site,
                    title=(j.get("text") or "").strip(),
                    apply_url=j.get("applyUrl") or j.get("hostedUrl"),
                    location=(cats.get("location") or "").strip() or None,
                    department=(cats.get("team") or "").strip() or None,
                    description_text=(j.get("descriptionBody") or j.get("description") or "").strip()
                    or None,
                    posted_at=j.get("createdAt"),
                    raw=j,
                )
            )
        return postings
