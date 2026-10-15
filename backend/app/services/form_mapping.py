"""候選人表單映射（FR-3b）：把用戶畫像/文件轉成投遞表單可用的字段集合。

原則（GAP-3）：缺失字段標記並交由人工接管，絕不編造。
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

# 投遞表單常見字段 → 數據來源描述
CRITICAL_FIELDS = ("full_name", "email", "phone")       # 缺了無法投遞
IMPORTANT_FIELDS = ("location", "visa_status", "resume_file", "education_entry")  # 缺了需人工確認


def build_candidate_payload(db: Session, user_id: str) -> dict:
    """合併 profiles + 當前畫像 + 文件庫，輸出投遞字段字典。"""
    profile = db.execute(
        text("SELECT id, email, phone, full_name FROM profiles WHERE id=:uid"),
        {"uid": user_id},
    ).mappings().first()
    cp = db.execute(
        text(
            "SELECT summary, skills, experiences, education, hard_facts, suggested_roles "
            "FROM candidate_profiles WHERE user_id=:uid AND is_current=true "
            "ORDER BY generated_at DESC LIMIT 1"
        ),
        {"uid": user_id},
    ).mappings().first()
    docs = db.execute(
        text(
            "SELECT doc_type, file_name, storage_path, parse_status FROM user_documents "
            "WHERE user_id=:uid AND deleted_at IS NULL AND is_active=true"
        ),
        {"uid": user_id},
    ).mappings().all()

    resume = next((d for d in docs if d["doc_type"] == "resume"), None)
    payload = {
        "full_name": (profile["full_name"] if profile else None) or (
            (cp["summary"] or "").split("，")[0].split(",")[0].strip() if cp else None
        ),
        "email": profile["email"] if profile else None,
        "phone": profile["phone"] if profile else None,
        "skills": (cp["skills"] if cp else None) or [],
        "experiences": (cp["experiences"] if cp else None) or [],
        "education": (cp["education"] if cp else None) or [],
        "education_entry": ((cp["education"] or [{}])[0] if cp and cp["education"] else None),
        "resume_file": {"name": resume["file_name"], "storage_path": resume["storage_path"]}
        if resume and resume["parse_status"] in ("parsed", "ocr") else None,
        "transcript_file": next(
            ({"name": d["file_name"], "storage_path": d["storage_path"]}
             for d in docs if d["doc_type"] == "transcript"), None),
        "visa_file": next(
            ({"name": d["file_name"], "storage_path": d["storage_path"]}
             for d in docs if d["doc_type"] == "visa"), None),
        "cover_letter_text": None,  # 由 optimize 服務注入
    }
    if cp and cp["hard_facts"]:
        payload.update(cp["hard_facts"])
    return payload


def missing_fields(payload: dict) -> dict:
    """返回 {critical: [...], important: [...]}。"""
    critical = [f for f in CRITICAL_FIELDS if not payload.get(f)]
    important = [f for f in IMPORTANT_FIELDS if not payload.get(f)]
    return {"critical": critical, "important": important}
