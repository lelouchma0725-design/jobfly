"""Moka 招聘系統採集器（app.mokahr.com）— 富途證券 futu5。

接口（2026-11 抓包 + 前端 JS 逆向實測）：
- 列表：POST /api/outer/ats-apply/website/jobs/v2
  body: {"orgId":"futu5","siteId":"141186","limit":30,"offset":0,
         "needStat":true,"jobIdTopList":[],"customFields":{},
         "site":"campus"|"social","locale":"zh-CN"}
- 響應加密：{"data": "<AES-128-CBC base64>", "necromancer": "<16字節密鑰>"}
  解密：key=necromancer(utf8)，iv=16 零字節，PKCS7。
- 明文結構：{type, data: {jobStats:{total}, jobs:[{id,title,locations[{cityName}],
  deptId,status,publishedAt,openedAt,...}]}}
"""
from __future__ import annotations

import base64
import json
import logging

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.collectors.base import JobPosting, register

logger = logging.getLogger(__name__)

# (orgId, siteId, site, 公司名, 應用 URL)
PORTALS = (
    ("futu5", "141186", "campus", "富途證券",
     "https://app.mokahr.com/m/campus_apply/futu5/141186",
     "de7c21ed8d6f50fe"),  # aesIv（門戶配置，頁面 TurboApply.data.aesIv）
)
SITES = ("campus", "social")  # 校園 / 社招（部分公司無社招入口，空列表即可）
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def _decrypt(data_b64: str, key: str, iv_str: str) -> dict:
    ct = base64.b64decode(data_b64)
    k = key.encode("utf-8")
    iv = iv_str.encode("utf-8") if iv_str else b"\x00" * 16
    cipher = Cipher(algorithms.AES(k), modes.CBC(iv))
    dec = cipher.decryptor()
    pt = dec.update(ct) + dec.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    pt = unpadder.update(pt) + unpadder.finalize()
    return json.loads(pt.decode("utf-8"))


def _fetch(org_id: str, site_id: str, site: str, offset: int, iv_str: str,
           limit: int = 30) -> tuple[list[dict], int]:
    resp = httpx.post(
        "https://app.mokahr.com/api/outer/ats-apply/website/jobs/v2",
        headers=HEADERS,
        json={"orgId": org_id, "siteId": site_id, "limit": limit, "offset": offset,
              "needStat": True, "jobIdTopList": [], "customFields": {},
              "site": site, "locale": "zh-CN"},
        timeout=25,
    )
    resp.raise_for_status()
    body = resp.json()
    if not body.get("data") or not body.get("necromancer"):
        return [], 0
    plain = _decrypt(body["data"], body["necromancer"], iv_str)
    data = plain.get("data") or {}
    jobs = data.get("jobs") or []
    total = (data.get("jobStats") or {}).get("total") or 0
    return jobs, int(total)


@register
class MokaCollector:
    name = "moka"

    def collect(self, target: dict) -> list[JobPosting]:
        org_id, site_id, _, company, apply_base, iv_str = PORTALS[0]
        postings: list[JobPosting] = []
        seen: set[str] = set()
        for site in SITES:
            offset = 0
            while offset < 2000:
                try:
                    jobs, total = _fetch(org_id, site_id, site, offset, iv_str)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("moka 採集失敗 site=%s off=%s: %s", site, offset, exc)
                    break
                if not jobs:
                    break
                for it in jobs:
                    key = str(it.get("id") or "")
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    locs = it.get("locations") or []
                    loc = "、".join(
                        f"{x.get('provinceName') or ''}{x.get('cityName') or ''}".strip("·")
                        for x in locs if isinstance(x, dict)
                    ) or None
                    title = str(it.get("title") or "").strip()
                    is_campus = site == "campus"
                    postings.append(JobPosting(
                        source="moka",
                        external_id=key,
                        company_name=company,
                        title=title,
                        apply_url=apply_base,
                        location=loc,
                        department=str(it.get("deptId") or "") or None,
                        description_text=f"富途證券（Moka 招聘門戶）：{title}",
                        posted_at=str(it.get("publishedAt") or "") or None,
                        raw={
                            "tab": "校園招聘" if is_campus else "社會招聘",
                            "is_campus": is_campus,
                            "is_intern": "實習" in title or "实习" in title,
                            **it,
                        },
                    ))
                offset += 30
                if offset >= total:
                    break
        return postings
