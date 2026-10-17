"""AI 用戶畫像服務（FR-1e）。"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.jsonutil import j
from app.core.llm import chat_json

_PROFILE_SYSTEM = """
你是一名職業規劃顧問。根據候選人簡歷生成用戶畫像與崗位推薦。
規則：
1. 只基於簡歷事實，嚴禁編造經歷、證書或簽證狀態。
2. 貼合度（fit_score, 50-100）要可解釋：技能重疊、經歷相關性、職級、地點。
3. 每個推薦崗位給出 2-3 條理由，以及一句市場需求說明。
輸出 JSON（不要輸出其他內容）：
{
  "candidate_name": "候選人真實姓名（簡歷首部姓名，無法確定則空字符串）",
  "summary": "一句話概覽",
  "skills": [{"name": "技能", "level": 1-5, "years": 年數或null}],
  "experiences": [{"company": "公司", "title": "職位", "start": "開始", "end": "結束", "bullets": ["要點"]}],
  "education": [{"school": "學校", "degree": "學位", "major": "專業", "start": "開始", "end": "結束"}],
  "hard_facts": {"visa_status": "簽證狀態或null", "preferred_locations": ["城市"], "salary_expectation": "期望薪資或null", "availability": "可到崗時間或null", "total_years": 年限數字或null},
  "suggested_roles": [{"title": "崗位", "fit_score": 50-100, "reasons": ["理由"], "demand_note": "市場需求一句話"}]  // 必須恰好 5 個，按 fit_score 從高到低排列
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

    # 推薦崗位：保證 5 個並按貼合度降序
    roles = profile.get("suggested_roles") or []
    roles.sort(key=lambda r: -(int(r.get("fit_score") or 0)))
    profile["suggested_roles"] = roles[:5]

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
            "skills": j(profile.get("skills") or []),
            "exp": j(profile.get("experiences") or []),
            "edu": j(profile.get("education") or []),
            "hf": j(profile.get("hard_facts") or {}),
            "roles": j(profile.get("suggested_roles") or []),
            "model": "deepseek-chat",  # TODO: 從 settings 讀取
        },
    ).mappings().one()
    db.commit()

    # ── 元信息表同步（畫像提取 → 個人信息庫，source=resume）──
    hf = profile.get("hard_facts") or {}
    hard_keys = {
        "visa_status": "簽證狀態", "preferred_locations": "期望城市",
        "salary_expectation": "期望薪資", "availability": "可到崗時間",
        "total_years": "工作年限",
    }
    for key in hard_keys:
        v = hf.get(key)
        if v in (None, "", []):
            continue
        db.execute(
            text(
                "INSERT INTO user_info_fields (user_id, key, value, source) VALUES (:u,:k,:v,'resume') "
                "ON CONFLICT (user_id, key) DO UPDATE SET value=EXCLUDED.value, "
                "source='resume', updated_at=now()"
            ),
            {"u": user_id, "k": key,
             "v": "、".join(v) if isinstance(v, list) else str(v)},
        )
    cname = str(profile.get("candidate_name") or "").strip()
    if cname:
        db.execute(
            text(
                "INSERT INTO user_info_fields (user_id, key, value, source) VALUES (:u,'candidate_name',:v,'resume') "
                "ON CONFLICT (user_id, key) DO UPDATE SET value=EXCLUDED.value, "
                "source='resume', updated_at=now()"
            ),
            {"u": user_id, "v": cname[:64]},
        )
        # 真實姓名回填 profiles.full_name（當前是佔位名時覆蓋）
        row_p = db.execute(
            text("SELECT full_name, email FROM profiles WHERE id=:u"), {"u": user_id}
        ).mappings().first()
        email_prefix = (row_p["email"] or "").split("@")[0] if row_p else ""
        if row_p is not None and (not row_p["full_name"]
                                  or row_p["full_name"] in ("管理員", email_prefix)):
            db.execute(
                text("UPDATE profiles SET full_name=:n, updated_at=now() WHERE id=:u"),
                {"n": cname[:64], "u": user_id},
            )
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
    # 統一視圖：元信息表覆蓋畫像硬性事實（兩處永不矛盾）
    info = db.execute(
        text("SELECT key, value FROM user_info_fields WHERE user_id=:uid"),
        {"uid": user_id},
    ).mappings().all()
    hf = dict(d.get("hard_facts") or {})
    for r in info:
        if r["key"] in hf or r["key"] in (
            "visa_status", "preferred_locations", "salary_expectation",
            "availability", "total_years", "candidate_name",
        ):
            v = r["value"]
            if r["key"] == "preferred_locations" and isinstance(hf.get("preferred_locations"), list):
                continue  # 期望城市以畫像列表為準
            hf[r["key"]] = v
    d["hard_facts"] = hf
    d["id"] = str(d["id"])
    d["based_on_resume_version_id"] = str(d["based_on_resume_version_id"]) if d["based_on_resume_version_id"] else None
    return d
