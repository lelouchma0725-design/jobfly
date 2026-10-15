"""AI 用戶畫像服務（FR-1e）。"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.llm import chat_json

_PROFILE_SYSTEM = """
你是一名職業規劃顧問。根據候選人簡歷生成用戶畫像與崗位推薦。
規則：
1. 只基於簡歷事實，嚴禁編造經歷、證書或簽證狀態。
2. 貼合度（fit_score, 50-100）要可解釋：技能重疊、經歷相關性、職級、地點。
3. 每個推薦崗位給出 2-3 條理由，以及一句市場需求說明。
輸出 JSON（不要輸出其他內容）：
{
  "summary": "一句話概覽",
  "skills": [{"name": "技能", "level": 1-5, "years": 年數或null}],
  "experiences": [{"company": "公司", "title": "職位", "start": "開始", "end": "結束", "bullets": ["要點"]}],
  "education": [{"school": "學校", "degree": "學位", "major": "專業", "start": "開始", "end": "結束"}],
  "hard_facts": {"visa_status": "簽證狀態或null", "preferred_locations": ["城市"], "salary_expectation": "期望薪資或null", "availability": "可到崗時間或null", "total_years": 年限數字或null},
  "suggested_roles": [{"title": "崗位", "fit_score": 50-100, "reasons": ["理由"], "demand_note": "市場需求一句話"}]
}
"""


def generate_profile(db: Session, user_id: str, resume_version_id: str | None = None) -> str:
    """基於最新（或指定）簡歷版本生成畫像，返回新畫像 ID。"""
    if resume_version_id:
        row = db.execute(
            text(
                "SELECT id, content_md FROM resume_versions "
                "WHERE id=:rid AND user_id=:uid"
            ),
            {"rid": resume_version_id, "uid": user_id},
        ).mappings().first()
    else:
        row = db.execute(
            text(
                "SELECT id, content_md FROM resume_versions "
                "WHERE user_id=:uid ORDER BY version_no DESC LIMIT 1"
            ),
            {"uid": user_id},
        ).mappings().first()
    if not row:
        raise ValueError("沒有可用的簡歷版本，請先上傳並解析簡歷")

    profile = chat_json(_PROFILE_SYSTEM, f"簡歷：\n{row['content_md'][:12000]}")

    # 舊畫像全部標記非當前
    db.execute(
        text("UPDATE candidate_profiles SET is_current=false WHERE user_id=:uid"),
        {"uid": user_id},
    )
    new_id = db.execute(
        text(
            """
            INSERT INTO candidate_profiles
              (user_id, based_on_resume_version_id, summary, skills, experiences,
               education, hard_facts, suggested_roles, model_used, is_current)
            VALUES (:uid, :rv, :summary, CAST(:skills AS jsonb), CAST(:exp AS jsonb),
                    CAST(:edu AS jsonb), CAST(:hf AS jsonb), CAST(:roles AS jsonb),
                    :model, true)
            RETURNING id
            """
        ),
        {
            "uid": user_id,
            "rv": row["id"],
            "summary": profile.get("summary"),
            "skills": profile.get("skills") or [],
            "exp": profile.get("experiences") or [],
            "edu": profile.get("education") or [],
            "hf": profile.get("hard_facts") or {},
            "roles": profile.get("suggested_roles") or [],
            "model": "deepseek-chat",  # TODO: 從 settings 讀取
        },
    ).mappings().one()
    db.commit()
    return str(new_id["id"])


def get_current_profile(db: Session, user_id: str) -> dict | None:
    row = db.execute(
        text(
            "SELECT * FROM candidate_profiles WHERE user_id=:uid AND is_current=true "
            "ORDER BY generated_at DESC LIMIT 1"
        ),
        {"uid": user_id},
    ).mappings().first()
    if not row:
        return None
    d = dict(row)
    d["id"] = str(d["id"])
    d["based_on_resume_version_id"] = str(d["based_on_resume_version_id"]) if d["based_on_resume_version_id"] else None
    return d
