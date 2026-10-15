"""文檔解析服務：文本抽取 → LLM 結構化（簡歷）。"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.jsonutil import j
from app.core.llm import chat_json
from app.services.parsing import extract_text, ocr_image

logger = logging.getLogger(__name__)

RESUME_SCHEMA = """
{
  "full_name": "姓名或空字符串",
  "email": "郵箱或null",
  "phone": "電話或null",
  "location": "現居城市或null",
  "current_role": "當前職位或null",
  "years_of_experience": 工作年限數字或null,
  "skills": [{"name": "技能名", "level": 1-5, "years": 使用年數或null}],
  "experiences": [{"company": "公司", "title": "職位", "start": "開始時間", "end": "結束時間或'至今'", "bullets": ["工作內容要點"]}],
  "education": [{"school": "學校", "degree": "學位", "major": "專業", "start": "開始", "end": "結束"}],
  "certificates": ["證書列表"],
  "languages": ["語言列表"],
  "visa_status": "簽證狀態或null（如 H1B/綠卡/中國大陸公民）",
  "preferred_roles": ["期望職位"],
  "preferred_locations": ["期望城市"],
  "salary_expectation": "期望薪資或null",
  "availability": "可到崗時間或null"
}
"""

_RESUME_SYSTEM = f"""
你是一名資深招聘顧問，負責把簡歷原文結構化。
規則：
1. 只提取簡歷中明確存在的信息，缺失的用 null 或空數組，嚴禁臆造。
2. 技能 level 按簡歷描述判斷（1 了解 / 3 熟練 / 5 專家），無依據給 3。
3. 時間格式統一為 YYYY-MM 或 YYYY。
4. 輸出 JSON 結構如下（不要輸出其他內容）：
{RESUME_SCHEMA}
"""


def parse_document(db: Session, doc_id: str, user_id: str, storage_path: str, mime: str) -> None:
    """解析單個文檔：文本抽取 → OCR 兜底 → LLM 結構化 → 落庫。

    簡歷類文檔同時生成 resume_versions 版本 1（原始版，永不覆蓋，GAP-4）。
    """
    db.execute(
        text("UPDATE user_documents SET parse_status='parsing', parse_error=NULL WHERE id=:id AND user_id=:uid"),
        {"id": doc_id, "uid": user_id},
    )
    db.commit()

    try:
        extracted_text, needs_ocr = extract_text(storage_path, mime)
        if needs_ocr:
            from app.services.parsing import download_bytes

            extracted_text = ocr_image(download_bytes(storage_path))
            db.execute(
                text("UPDATE user_documents SET parse_status='ocr' WHERE id=:id"),
                {"id": doc_id},
            )
        if not extracted_text.strip():
            raise RuntimeError("未能從文件中抽取到任何文本")

        doc_type = db.execute(
            text("SELECT doc_type FROM user_documents WHERE id=:id"), {"id": doc_id}
        ).mappings().one()["doc_type"]

        if doc_type in ("resume", "cover_letter"):
            structured = chat_json(_RESUME_SYSTEM, f"簡歷原文：\n{extracted_text[:12000]}")
            db.execute(
                text(
                    """
                    UPDATE user_documents
                    SET parsed_text=:txt, structured_json=CAST(:sj AS jsonb),
                        parse_status='parsed', parse_error=NULL
                    WHERE id=:id
                    """
                ),
                {"id": doc_id, "txt": extracted_text, "sj": j(structured)},
            )
            if doc_type == "resume":
                _create_resume_version(db, doc_id, user_id, extracted_text, structured)
        else:
            db.execute(
                text(
                    """
                    UPDATE user_documents
                    SET parsed_text=:txt, parse_status='parsed', parse_error=NULL
                    WHERE id=:id
                    """
                ),
                {"id": doc_id, "txt": extracted_text},
            )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("文檔解析失敗 doc=%s", doc_id)
        db.execute(
            text(
                "UPDATE user_documents SET parse_status='failed', parse_error=:err WHERE id=:id"
            ),
            {"id": doc_id, "err": str(exc)[:2000]},
        )
        db.commit()
        raise


def _create_resume_version(
    db: Session, doc_id: str, user_id: str, raw_text: str, structured: dict
) -> None:
    """把解析結果落成 resume_versions 版本 1（原始版）。"""
    version_no = db.execute(
        text(
            "SELECT COALESCE(MAX(version_no), 0) + 1 AS n FROM resume_versions WHERE user_id = :uid"
        ),
        {"uid": user_id},
    ).mappings().one()["n"]

    db.execute(
        text(
            """
            INSERT INTO resume_versions
              (user_id, source_document_id, version_no, content_md, created_by)
            VALUES (:uid, :doc, :vn, :content, 'user')
            ON CONFLICT (user_id, version_no) DO NOTHING
            """
        ),
        {
            "uid": user_id,
            "doc": doc_id,
            "vn": version_no,
            "content": _structured_to_markdown(structured) or raw_text[:30000],
        },
    )
    db.commit()


def _structured_to_markdown(s: dict) -> str:
    lines: list[str] = []
    if s.get("full_name"):
        lines.append(f"# {s['full_name']}")
    contact = " | ".join(x for x in (s.get("email"), s.get("phone"), s.get("location")) if x)
    if contact:
        lines.append(contact)
    for edu in s.get("education") or []:
        lines.append(
            f"- 教育：{edu.get('school')} {edu.get('degree')} {edu.get('major')} "
            f"({edu.get('start')} - {edu.get('end')})"
        )
    for exp in s.get("experiences") or []:
        lines.append(f"\n## {exp.get('title')} @ {exp.get('company')} ({exp.get('start')} - {exp.get('end')})")
        for b in exp.get("bullets") or []:
            lines.append(f"- {b}")
    skills = ", ".join(sk["name"] for sk in s.get("skills") or [])
    if skills:
        lines.append(f"\n## 技能\n{skills}")
    return "\n".join(lines)
