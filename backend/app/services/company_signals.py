"""公司信號：行業/規模/地區分類（LLM + 緩存）與香港崗位精細化加權。

v1 規則（可由用戶調整）：
- 規模：small(0-50) -5；medium(50-200) 0；large(200+) +5；unknown 0
- 行業：insurance -6；tech +4；finance +4；other 0
- 崗位-公司行業一致：+4；不一致 -3；unknown 0
總調整區間 [-14, +13]，作用於 priority_score（貼合度 match_score 不變）。
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.jsonutil import j, loads_json
from app.core.llm import chat_json

logger = logging.getLogger(__name__)

CLASSIFY_SYSTEM = """你是香港求職市場分析師。根據公司名與崗位信息，輸出 JSON：
{"company_industry": "tech|finance|insurance|other",
 "size_bucket": "small|medium|large|unknown",
 "job_industry": "tech|finance|insurance|other",
 "company_size_note": "一句話說明規模判斷依據"}
規則：
- size_bucket 按員工人數：small=0-50 人；medium=50-200 人；large=200 人以上；無法判斷填 unknown
- company_industry：保險/經紀行→insurance；銀行/券商/資管/基金/對沖→finance；軟件/互聯網/IT/數據/AI→tech；其他→other
- job_industry：按崗位標題+職責判斷屬於哪類
- 只輸出 JSON，不要其他文字"""

SIZE_ADJ = {"small": -5, "medium": 0, "large": 5, "unknown": 0}
INDUSTRY_ADJ = {"insurance": -6, "tech": 4, "finance": 4, "other": 0}
ALIGN_ADJ = {"same": 4, "diff": -3, "unknown": 0}


def classify_company(db: Session, company_name: str, job_hint: str) -> dict:
    """公司分類（緩存按公司名）+ 崗位行業判斷（每次計算）。"""
    company_name = (company_name or "").strip()[:200]
    row = db.execute(
        text("SELECT * FROM company_profiles WHERE company_name=:n"),
        {"n": company_name},
    ).mappings().first()
    if not row or not row.get("industry"):
        try:
            out = chat_json(CLASSIFY_SYSTEM, f"公司名：{company_name}\n崗位：{job_hint[:600]}", max_tokens=300)
        except Exception:  # noqa: BLE001
            logger.exception("公司分類失敗 %s", company_name)
            out = {}
        industry = str(out.get("company_industry") or "other")
        size = str(out.get("size_bucket") or "unknown")
        db.execute(
            text(
                "INSERT INTO company_profiles (company_name, industry, size_bucket, region, extra) "
                "VALUES (:n, :i, :s, 'hk', CAST(:e AS jsonb)) "
                "ON CONFLICT (company_name) DO UPDATE SET industry=EXCLUDED.industry, "
                "size_bucket=EXCLUDED.size_bucket, extra=EXCLUDED.extra, updated_at=now()"
            ),
            {"n": company_name, "i": industry, "s": size,
             "e": j({"size_note": str(out.get("company_size_note") or "")})},
        )
        db.commit()
        return {
            "company_industry": industry,
            "size_bucket": size,
            "job_industry": str(out.get("job_industry") or "other"),
        }
    extra = loads_json(row.get("extra")) if isinstance(row.get("extra"), str) else (row.get("extra") or {})
    # 崗位行業每次重新判斷（與具體崗位相關）
    job_industry = "other"
    try:
        out2 = chat_json(CLASSIFY_SYSTEM, f"公司名：{company_name}\n崗位：{job_hint[:600]}", max_tokens=200)
        job_industry = str(out2.get("job_industry") or "other")
    except Exception:  # noqa: BLE001
        pass
    return {
        "company_industry": row["industry"],
        "size_bucket": row["size_bucket"],
        "job_industry": job_industry,
    }


def hk_adjust(sig: dict) -> tuple[int, dict]:
    """香港崗位精細化加權。返回 (調整分, 明細)。"""
    size_adj = SIZE_ADJ.get(sig.get("size_bucket") or "unknown", 0)
    industry_adj = INDUSTRY_ADJ.get(sig.get("company_industry") or "other", 0)
    ci = sig.get("company_industry") or "other"
    ji = sig.get("job_industry") or "other"
    align = "same" if ci != "other" and ci == ji else ("diff" if ci != "other" and ji != "other" else "unknown")
    align_adj = ALIGN_ADJ[align]
    detail = {
        "company_industry": ci,
        "size_bucket": sig.get("size_bucket") or "unknown",
        "job_industry": ji,
        "size_adjust": size_adj,
        "industry_adjust": industry_adj,
        "align_adjust": align_adj,
        "hk_adjust_total": size_adj + industry_adj + align_adj,
    }
    return size_adj + industry_adj + align_adj, detail
