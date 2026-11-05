"""AI 簡歷微調與 Cover Letter 生成（FR-1c / FR-3b，GAP-4 防造假）。

- 只允許重組/潤色簡歷中已有事實，禁止新增經歷、證書、簽證狀態
- 每次微調生成新 resume_versions 行（base_version_id 指向原版），保留 diff_summary 審計
- Cover Letter 存回同一版本的 cover_letter_md
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.llm import chat, chat_json

logger = logging.getLogger(__name__)

_OPTIMIZE_SYSTEM = """
你是一名專業簡歷顧問。根據 JD 微調候選人簡歷。
鐵律：
1. 只能重新組織、強調、換措辭簡歷中已存在的事實；嚴禁新增任何經歷、公司、學校、證書、技能或簽證信息。
2. 保持事實準確：時間、公司名、職位名不得改變。
3. 突出與 JD 要求相關的技能與成果，相關性低的內容可以壓縮但不得刪除關鍵事實。
4. 直接輸出微調後的簡歷 markdown，不要任何解釋。
"""

_DIFF_SYSTEM = """
對比原簡歷與微調後簡歷，用一句話（50字內）說明做了哪些調整（如"強調了 XX 技能並前置了 YY 經歷"）。只輸出這一句話。
"""

_CL_SYSTEM = """
你是一名求職輔導專家。根據候選人簡歷和 JD 撰寫一封 Cover Letter。
鐵律：只能使用簡歷中已有的事實，嚴禁編造經歷、技能或成就。
結構：開頭（對公司/崗位的熱情，一句話）、2-3 段正文（匹配的技能與經歷，用簡歷事實）、結尾（期待面試）。
輸出純文本，300-500 字，不要輸出其他內容。
"""


def optimize_resume_for_jd(
    db: Session, user_id: str, base_version_id: str, jd_text: str
) -> str | None:
    """微調簡歷：創建新版本並返回 version id；失敗返回 None（不阻塞投遞）。"""
    base = db.execute(
        text("SELECT content_md, version_no FROM resume_versions WHERE id=:id AND user_id=:uid"),
        {"id": base_version_id, "uid": user_id},
    ).mappings().first()
    if not base or not base["content_md"]:
        return None
    try:
        optimized = chat(
            _OPTIMIZE_SYSTEM,
            f"JD：\n{jd_text[:6000]}\n\n原簡歷：\n{base['content_md'][:8000]}",
            max_tokens=4000,
        )
        if not optimized.strip():
            return None
        diff = chat(_DIFF_SYSTEM, f"原簡歷：\n{base['content_md'][:3000]}\n\n微調後：\n{optimized[:3000]}")
        version_no = db.execute(
            text("SELECT COALESCE(MAX(version_no),0)+1 AS n FROM resume_versions WHERE user_id=:uid"),
            {"uid": user_id},
        ).mappings().one()["n"]
        new_id = db.execute(
            text(
                """
                INSERT INTO resume_versions
                  (user_id, base_version_id, version_no, content_md, created_by,
                   optimization_prompt, diff_summary)
                VALUES (:uid, :base, :vn, :content, 'ai', :jd, :diff)
                RETURNING id
                """
            ),
            {"uid": user_id, "base": base_version_id, "vn": version_no,
             "content": optimized, "jd": jd_text[:2000], "diff": diff[:300]},
        ).mappings().one()
        db.commit()
        return str(new_id["id"])
    except Exception:  # noqa: BLE001
        logger.exception("簡歷微調失敗 user=%s", user_id)
        return None


def generate_cover_letter(db: Session, user_id: str, resume_content: str, jd_text: str) -> str | None:
    try:
        cl = chat(
            _CL_SYSTEM,
            f"JD：\n{jd_text[:6000]}\n\n候選人簡歷：\n{resume_content[:8000]}",
            max_tokens=1500,
        )
        return cl.strip() or None
    except Exception:  # noqa: BLE001
        logger.exception("Cover Letter 生成失敗 user=%s", user_id)
        return None


def attach_cover_letter(db: Session, version_id: str, cover_letter: str) -> None:
    db.execute(
        text("UPDATE resume_versions SET cover_letter_md=:cl WHERE id=:id"),
        {"cl": cover_letter, "id": version_id},
    )
    db.commit()
