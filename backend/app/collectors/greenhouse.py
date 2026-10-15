"""Greenhouse 適配器（公開 Boards API，無需登錄）。

API 文檔: https://developers.greenhouse.io/job-board.html
- 列表: GET /v1/boards/{board_token}/jobs
- 詳情: GET /v1/boards/{board_token}/jobs/{job_id}（含 JD content）

board_token 從 careers_url 解析：
  https://boards.greenhouse.io/cloudflare → cloudflare
  https://boards.greenhouse.io/embed/job_board?for=cloudflare → cloudflare
"""
from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urlparse

import httpx

from app.collectors.base import JobPosting, register

logger = logging.getLogger(__name__)

BOARD_TOKEN_PATTERNS = (
    re.compile(r"[?&]for=([\w-]+)"),                      # embed/job_board?for=xxx 優先
    re.compile(r"boards\.greenhouse\.io/(?!embed)([\w-]+)(?:/|$|\?)"),
)

DETAIL_FETCH_LIMIT = 30   # 每輪最多抓取詳情數（控制請求量）
DETAIL_DELAY_S = 0.4      # 詳情請求間隔，避免觸發限流
DETAIL_RETRIES = 2


def _parse_board_token(careers_url: str) -> str | None:
    for pat in BOARD_TOKEN_PATTERNS:
        m = pat.search(careers_url)
        if m:
            return m.group(1)
    return None


def _list_jobs(board_token: str, timeout: float = 20.0) -> list[dict]:
    resp = httpx.get(
        f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs",
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 (JobFly/0.1)"},
    )
    resp.raise_for_status()
    return resp.json().get("jobs") or []


def _job_detail(board_token: str, job_id: int, timeout: float = 20.0) -> dict | None:
    import time

    for attempt in range(DETAIL_RETRIES + 1):
        try:
            resp = httpx.get(
                f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}",
                timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0 (JobFly/0.1)"},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            if attempt >= DETAIL_RETRIES:
                logger.warning("greenhouse 詳情抓取失敗 job=%s: %s", job_id, exc)
                return None
            time.sleep(DETAIL_DELAY_S * (attempt + 1))
    return None


@register
class GreenhouseCollector:
    name = "greenhouse"

    def collect(self, target: dict) -> list[JobPosting]:
        url = target.get("careers_url") or ""
        board = _parse_board_token(url)
        if not board:
            raise ValueError(f"無法從 URL 解析 Greenhouse board token: {url}")
        jobs = _list_jobs(board)
        postings: list[JobPosting] = []
        for j in jobs[:200]:
            jid = str(j["id"])
            loc = j.get("location") or {}
            postings.append(
                JobPosting(
                    source="greenhouse",
                    external_id=jid,
                    company_name=j.get("company_name") or target.get("company_name") or board,
                    title=j.get("title") or "",
                    apply_url=j.get("absolute_url"),
                    location=loc.get("name") if isinstance(loc, dict) else str(loc),
                    posted_at=j.get("first_published") or j.get("updated_at"),
                    raw=j,
                )
            )
        # 詳情補全（僅前 N 條，加延遲避免限流；描述缺失的崗位由下次更新補齊）
        import time

        for p in postings[:DETAIL_FETCH_LIMIT]:
            detail = _job_detail(board, int(p.external_id))
            if detail:
                p.description_text = (detail.get("content") or "").strip()
                p.department = (detail.get("departments") or [{}])[0].get("name")
            time.sleep(DETAIL_DELAY_S)
        return postings
