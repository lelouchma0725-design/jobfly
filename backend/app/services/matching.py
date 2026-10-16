"""貼合度匹配服務（FR-1f，GAP-12 雙層評分）。

第一層：硬性條件逐項核對（學歷/年限/簽證/語言/證書/地點），任一不滿足 → hard_failed。
第二層：LLM 綜合評分（50-100）+ 分項 + 可解釋理由。
結果 upsert 到 job_matches；status 由 auto_apply_mode 在投遞階段消費。
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.jsonutil import j
from app.core.llm import chat_json

_HARD_SYSTEM = """
你是一名招聘顧問。從 JD 中抽取硬性要求。
規則：
1. kind 取值：education(學歷/專業)、experience_years(工作年限)、visa(簽證/身份)、language(語言)、certificate(證書)、location(工作地點/在場要求)、other。
2. must=true 表示"必須滿足"類要求（如"要求本科以上"、"需持綠卡"）；偏好類要求 must=false。
3. requirement 用一句話描述。
輸出 JSON（不要輸出其他內容）：
{"requirements": [{"field": "字段名", "kind": "...", "requirement": "描述", "must": true}]}
"""

_SCORE_SYSTEM = """
你是一名招聘顧問。綜合評估候選人與 JD 的貼合度，輸出 50-100 分。
規則：
1. 評分依據：技能重疊、經歷相關性、職級匹配、地點、薪資預期。
2. 若 JD 有硬性要求候選人不滿足，不要評分（此場景由系統先過濾，你不會收到）。
3. 給出三條簡潔可執行的理由（如"缺 XX 技能，可補充學習"）。
輸出 JSON（不要輸出其他內容）：
{"match_score": 50-100, "breakdown": {"skills_overlap": 0-100, "experience_fit": 0-100, "level_fit": 0-100, "location_fit": 0-100, "salary_fit": 0-100}, "reasons": ["理由1", "理由2", "理由3"]}
"""


def extract_hard_requirements(jd_text: str) -> list[dict]:
    out = chat_json(_HARD_SYSTEM, f"JD：\n{jd_text[:8000]}")
    return [r for r in (out.get("requirements") or []) if r.get("must")]


def _check_against(profile: dict, req: dict) -> bool:
    """簡化的規則核對 + 兜底。返回是否通過。"""
    kind = req.get("kind")
    requirement = (req.get("requirement") or "").lower()
    hard = profile.get("hard_facts") or {}

    if kind == "experience_years":
        years = hard.get("total_years")
        if years is None:
            return True  # 無法核對不攔截，交由 LLM 評分
        import re

        m = re.search(r"(\d+)", requirement)
        return years >= int(m.group(1)) if m else True
    if kind == "visa":
        return bool(hard.get("visa_status"))  # 有簽證信息即放行，細粒度在 LLM 評分
    if kind == "language":
        langs = " ".join(profile.get("languages") or [])
        return bool(langs)
    if kind == "certificate":
        certs = " ".join(profile.get("certificates") or [])
        return bool(certs)
    if kind == "location":
        locs = " ".join(hard.get("preferred_locations") or [])
        return bool(locs)
    return True


def score_posting(db: Session, user_id: str, posting_id: str) -> dict:
    """對單個崗位執行雙層評分並落庫。返回 match 記錄。"""
    profile = db.execute(
        text(
            "SELECT * FROM candidate_profiles WHERE user_id=:uid AND is_current=true "
            "ORDER BY generated_at DESC LIMIT 1"
        ),
        {"uid": user_id},
    ).mappings().first()
    posting = db.execute(
        text("SELECT * FROM job_postings WHERE id=:pid"),
        {"pid": posting_id},
    ).mappings().first()
    if not profile:
        raise ValueError("請先生成用戶畫像")
    if not posting:
        raise ValueError("崗位不存在")

    hard_reqs = extract_hard_requirements(posting["description_text"] or posting["title"])
    # location 類要求不硬攔截（交給地區加權處理：命中加分、未命中降分）
    failures = [
        r for r in hard_reqs
        if r.get("kind") != "location" and not _check_against(dict(profile), r)
    ]

    # 校招/社招偏好與職級適配（投遞規則 R2 修訂版）：
    # - 用戶偏好只投社招 → 校招崗位硬性過濾
    # - 用戶允許投校招 → 有工作經歷者不攔截，但降權（職級不適配）
    campus_adjust = 0
    st = db.execute(
        text("SELECT campus_preference FROM user_settings WHERE user_id=:u"),
        {"u": user_id},
    ).mappings().first()
    preference = (st["campus_preference"] if st else "both") or "both"
    is_campus = bool(posting.get("is_campus")) or _is_campus_posting(posting)
    years = (dict(profile).get("hard_facts") or {}).get("total_years") or 0
    if is_campus and preference == "society":
        failures.append({
            "field": "campus_preference",
            "kind": "other",
            "requirement": "用戶設置為只投社招，校招崗位已過濾",
            "passed": False,
        })
    elif is_campus and years >= 1:
        campus_adjust = -15  # 校招職級不適配（有工作經歷）降權
    elif (not is_campus) and preference == "campus":
        failures.append({
            "field": "campus_preference",
            "kind": "other",
            "requirement": "用戶設置為只投校招，社招崗位已過濾",
            "passed": False,
        })

    if failures:
        db.execute(
            text(
                """
                INSERT INTO job_matches (user_id, posting_id, profile_version_id, hard_failures, status)
                VALUES (:uid, :pid, :pv, CAST(:hf AS jsonb), 'hard_failed')
                ON CONFLICT (user_id, posting_id) DO UPDATE
                  SET hard_failures=EXCLUDED.hard_failures, status='hard_failed', updated_at=now()
                """
            ),
            {"uid": user_id, "pid": posting_id, "pv": profile["id"], "hf": j(failures)},
        )
        db.commit()
        return {"match_score": None, "hard_failures": failures, "status": "hard_failed"}

    jd = (posting["description_text"] or "")[:8000]
    prompt = (
        f"候選人概覽：{profile['summary']}\n"
        f"技能：{profile['skills']}\n"
        f"經歷：{profile['experiences']}\n"
        f"硬性事實：{profile['hard_facts']}\n\n"
        f"JD：{jd}"
    )
    scored = chat_json(_SCORE_SYSTEM, prompt)

    # 地區權重調整（期望城市加權，非期望城市適度降權）+ 校招職級適配
    adjustment = _location_adjust(db, user_id, posting["location"]) + campus_adjust
    final_score = int(scored["match_score"]) + adjustment
    final_score = min(max(final_score, 50), 100)
    breakdown = scored.get("breakdown") or {}
    breakdown["location_adjust"] = adjustment - campus_adjust
    breakdown["campus_adjust"] = campus_adjust

    db.execute(
        text(
            """
            INSERT INTO job_matches
              (user_id, posting_id, profile_version_id, match_score, score_breakdown, reasons, status)
            VALUES (:uid, :pid, :pv, :score, CAST(:bd AS jsonb), CAST(:reasons AS jsonb), 'new')
            ON CONFLICT (user_id, posting_id) DO UPDATE
              SET match_score=EXCLUDED.match_score, score_breakdown=EXCLUDED.score_breakdown,
                  reasons=EXCLUDED.reasons, hard_failures=NULL,
                  status=CASE WHEN job_matches.status IN ('applied','applying') THEN job_matches.status ELSE 'new' END,
                  updated_at=now()
            """
        ),
        {
            "uid": user_id,
            "pid": posting_id,
            "pv": profile["id"],
            "score": final_score,
            "bd": j(breakdown),
            "reasons": j(scored.get("reasons") or []),
        },
    )
    db.commit()
    return {"match_score": final_score, "hard_failures": [], "status": "new",
            "location_adjust": adjustment}


def _is_campus_posting(posting: dict) -> bool:
    """判斷是否校招/應屆類崗位（標題/JD/採集元數據）。"""
    text = " ".join([
        posting.get("title") or "",
        posting.get("description_text") or "",
        str((posting.get("raw") or {}).get("tab") or ""),
        str((posting.get("raw") or {}).get("recruit_type") or ""),
    ]).lower()
    hints = ("校招", "校园", "应届", "應屆", "管培生", "培训生", "培訓生", "秋招", "春招", "2027届", "2027屆")
    return any(h in text for h in hints)


def _location_adjust(db: Session, user_id: str, posting_location: str | None) -> int:
    """期望城市命中 +location_weight；未命中且配置了期望城市 → -min(weight,10)。"""
    st = db.execute(
        text("SELECT preferred_locations, location_weight FROM user_settings WHERE user_id=:u"),
        {"u": user_id},
    ).mappings().first()
    preferred = (st["preferred_locations"] if st else None) or []
    weight = (st["location_weight"] if st else None) or 10
    if not preferred:
        return 0
    loc = (posting_location or "").lower()
    if any(p.lower() in loc for p in preferred):
        return weight
    return -min(weight, 10)
