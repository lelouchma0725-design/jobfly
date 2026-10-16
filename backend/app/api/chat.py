"""AI 求職管家對話端點（首頁 Chatbot）。

LLM 通過工具（function calling）直接操作用戶數據：
查詢畫像/匹配/投遞/待處理、觸發採集、修改設置、首次使用引導。
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.collectors.pipeline import collect_for_user
from app.core.auth import get_current_user
from app.core.llm import chat_with_tools
from app.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


SYSTEM_PROMPT = """
你是 JobsComing 的 AI 求職管家，幫助用戶管理簡歷投遞全流程。
規則：
1. 用繁體中文、口語化、簡潔（一般 2-5 句）回覆，適當用列表。
2. 主動使用工具獲取真實數據，不要憑空編造；工具返回的就是事實。
3. 用戶想了解狀態/執行操作時，先調工具再總結。
4. 需要用戶操作時給出明確的一步步指引（例如去哪個頁面點什麼）。
5. 首次使用的用戶（沒有畫像/簡歷/關注公司）主動引導：上傳簡歷→生成畫像→添加公司→開啟自動投遞。
6. 不要洩露任何密碼、token 等敏感信息。
"""


def _build_tools(user_id: str, db: Session) -> tuple[list[dict], callable]:
    def get_status(_: dict) -> dict:
        row = db.execute(text(
            """
            SELECT
              (SELECT COUNT(*) FROM candidate_profiles WHERE user_id=:u AND is_current=true) AS has_profile,
              (SELECT COUNT(*) FROM user_documents WHERE user_id=:u AND doc_type='resume' AND deleted_at IS NULL) AS resumes,
              (SELECT COUNT(*) FROM watched_companies WHERE user_id=:u AND is_active=true) AS companies,
              (SELECT COUNT(*) FROM job_matches m WHERE m.user_id=:u AND m.match_score IS NOT NULL AND m.status IN ('new','pushed')) AS new_matches,
              (SELECT COUNT(*) FROM applications a WHERE a.user_id=:u AND a.status='submitted') AS submitted,
              (SELECT COUNT(*) FROM applications a WHERE a.user_id=:u AND a.status IN ('queued','in_progress','failed_retryable')) AS in_progress,
              (SELECT COUNT(*) FROM manual_tasks t WHERE t.user_id=:u AND t.status='open') AS open_tasks
            """
        ), {"u": user_id}).mappings().one()
        st = db.execute(text(
            "SELECT match_threshold, auto_apply_mode FROM user_settings WHERE user_id=:u"
        ), {"u": user_id}).mappings().first()
        return {
            "畫像": "已生成" if row["has_profile"] else "未生成",
            "簡歷": row["resumes"],
            "關注公司": row["companies"],
            "新匹配崗位": row["new_matches"],
            "已投遞": row["submitted"],
            "處理中/排隊": row["in_progress"],
            "待人工處理": row["open_tasks"],
            "貼合度閾值": (st["match_threshold"] if st else 70),
            "投遞模式": (st["auto_apply_mode"] if st else "threshold"),
        }

    def guide(_: dict) -> dict:
        s = get_status({})
        missing = []
        if s["簡歷"] == 0:
            missing.append("上傳簡歷（首頁→我的資料→我的文件）")
        if s["畫像"] == "未生成":
            missing.append("生成 AI 畫像（我的資料→我的畫像→生成畫像）")
        if s["關注公司"] == 0:
            missing.append("添加關注公司（我的資料→關注公司）")
        if s["投遞模式"] == "off":
            missing.append("開啟自動投遞（我的資料→投遞設置→投遞模式）")
        return {"缺失步驟": missing or ["全部完成 ✅"]}

    def run_collect(_: dict) -> dict:
        try:
            report = collect_for_user(db, user_id)
            return {"完成": True, "本次新增崗位": report["new"],
                    "匹配": report["matched"], "錯誤": report["errors"]}
        except Exception as exc:  # noqa: BLE001
            logger.exception("chat 採集失敗")
            return {"完成": False, "原因": str(exc)[:200]}

    def list_matches(args: dict) -> dict:
        limit = min(int(args.get("limit", 5)), 20)
        rows = db.execute(text(
            """
            SELECT p.company_name, p.title, p.location, m.match_score, m.status
            FROM job_matches m JOIN job_postings p ON p.id=m.posting_id
            WHERE m.user_id=:u AND m.match_score IS NOT NULL AND m.status IN ('new','pushed','applied')
            ORDER BY m.match_score DESC LIMIT :n
            """
        ), {"u": user_id, "n": limit}).mappings().all()
        return {"匹配": [dict(r) for r in rows]}

    def list_applications(args: dict) -> dict:
        limit = min(int(args.get("limit", 5)), 20)
        rows = db.execute(text(
            """
            SELECT p.company_name, p.title, a.status, a.status_reason, a.updated_at
            FROM applications a JOIN job_postings p ON p.id=a.posting_id
            WHERE a.user_id=:u ORDER BY a.updated_at DESC LIMIT :n
            """
        ), {"u": user_id, "n": limit}).mappings().all()
        return {"投遞": [dict(r) for r in rows]}

    def list_tasks(args: dict) -> dict:
        rows = db.execute(text(
            """
            SELECT t.task_type, t.question, t.created_at,
                   p.company_name, p.title
            FROM manual_tasks t
            JOIN applications a ON a.id=t.application_id
            JOIN job_postings p ON p.id=a.posting_id
            WHERE t.user_id=:u AND t.status='open' ORDER BY t.created_at DESC LIMIT 5
            """
        ), {"u": user_id}).mappings().all()
        return {"待處理": [dict(r) for r in rows]}

    def update_settings(args: dict) -> dict:
        fields = {}
        if "match_threshold" in args:
            fields["match_threshold"] = min(max(int(args["match_threshold"]), 50), 100)
        if "auto_apply_mode" in args and args["auto_apply_mode"] in ("off", "threshold", "all"):
            fields["auto_apply_mode"] = args["auto_apply_mode"]
        if not fields:
            return {"完成": False, "原因": "沒有可更新的設置"}
        sets = ", ".join(f"{k}=:{k}" for k in fields)
        db.execute(text(
            "INSERT INTO user_settings (user_id) VALUES (:u) ON CONFLICT (user_id) DO NOTHING"
        ), {"u": user_id})
        db.execute(text(
            f"UPDATE user_settings SET {sets}, updated_at=now() WHERE user_id=:u"
        ), {"u": user_id, **fields})
        db.commit()
        return {"完成": True, "已更新": fields}

    tools = [
        {"type": "function", "function": {
            "name": "get_status",
            "description": "查詢用戶當前整體狀態（畫像/簡歷/匹配/投遞/待處理/設置）",
            "parameters": {"type": "object", "properties": {}},
        }},
        {"type": "function", "function": {
            "name": "guide",
            "description": "檢查首次使用還缺哪些步驟",
            "parameters": {"type": "object", "properties": {}},
        }},
        {"type": "function", "function": {
            "name": "run_collect",
            "description": "立即採集用戶所有關注公司的最新崗位並匹配（可能耗時數分鐘，同步執行）",
            "parameters": {"type": "object", "properties": {}},
        }},
        {"type": "function", "function": {
            "name": "list_matches",
            "description": "列出用戶的最新匹配崗位（按貼合度排序）",
            "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
        }},
        {"type": "function", "function": {
            "name": "list_applications",
            "description": "列出用戶最近的投遞記錄與狀態",
            "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
        }},
        {"type": "function", "function": {
            "name": "list_tasks",
            "description": "列出等待用戶處理的人工任務（驗證碼/缺字段等）",
            "parameters": {"type": "object", "properties": {}},
        }},
        {"type": "function", "function": {
            "name": "update_settings",
            "description": "修改用戶設置：match_threshold(50-100) 或 auto_apply_mode(off/threshold/all)",
            "parameters": {"type": "object", "properties": {
                "match_threshold": {"type": "integer"},
                "auto_apply_mode": {"type": "string", "enum": ["off", "threshold", "all"]},
            }},
        }},
    ]
    executor = {
        "get_status": get_status,
        "guide": guide,
        "run_collect": run_collect,
        "list_matches": list_matches,
        "list_applications": list_applications,
        "list_tasks": list_tasks,
        "update_settings": update_settings,
    }
    return tools, lambda name, args: executor[name](args or {})


@router.post("")
def chat(user: CurrentUser, db: DB, payload: ChatRequest) -> dict:
    messages = [{"role": m.role, "content": m.content} for m in payload.messages[-10:]]
    tools, executor = _build_tools(user["id"], db)
    reply = chat_with_tools(SYSTEM_PROMPT, messages, tools, executor)
    return {"reply": reply}
