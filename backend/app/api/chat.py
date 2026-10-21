"""AI 求職管家對話端點（首頁 Chatbot）。

LLM 通過工具（function calling）直接操作用戶數據：
查詢畫像/匹配/投遞/待處理、觸發採集、修改設置、首次使用引導。
"""
from __future__ import annotations

import logging
import re
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.collectors.pipeline import collect_for_user
from app.core.auth import get_current_user
from app.core.jsonutil import j
from app.core.llm import chat_json, chat_with_tools
from app.db import SessionLocal, get_db

# 繁→簡 對照（成對排列，索引偶數為繁、奇數為簡）
_T2S_PAIRS = (
    "產产品品經经理理開开发发發发經经验验數数據据應应屆届培培訓训員员務务職职證证聯联网网點点類类銀银資资讯讯質质動动範范組组织织級级實实习习業业專专门门間间時时机机構构規规畫画計计設设銷销場场營营錢钱術术歷历係系國国體体單单與与讀读種种長长風风控控優优權权廣广东东亞亚險险斷断檔档待待校校園园崗岗簡简選选擇择請请填填寫写郵邮箱箱畢毕學学戶户籍籍城城市市農农村村金金融融練练員员續续務务業业個个國国際际證证務务處处體体係系號号臺台灣湾香香港港滬沪深深圳圳京京穗穗"
)


def _t2s(text: str) -> str:
    """繁體轉簡體（成對字符串，容錯任何空格/標點）。"""
    pairs = [c for c in _T2S_PAIRS if not c.isspace()]
    m = {pairs[i]: pairs[i + 1] for i in range(0, len(pairs) - 1, 2)}
    return "".join(m.get(ch, ch) for ch in text)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    conversation_id: str | None = None


SYSTEM_PROMPT = """
你是 JobsComing 的 AI 求職管家，幫助用戶管理簡歷投遞全流程。
規則：
1. 用繁體中文、口語化、簡潔（一般 2-5 句）回覆，適當用列表。
2. 主動使用工具獲取真實數據，不要憑空編造；工具返回的就是事實。
3. 用戶查詢具體崗位/職位名稱（例如「XX公司的XX崗位」「幫我找XX職位」）時，**必須調用 find_job 工具**，
   用頓號/逗號分隔的多個職位名要逐一調用 find_job 查詢；不要用 list_matches 代替、不要直接說沒有。
   find_job 查不到時，先調 run_collect 採集該公司最新崗位再重新查一次。
4. 用戶問某個崗位的貼合度時，必須調用 score_job（現場重算，保證數據最新）。
5. 用戶想了解狀態/執行操作時，先調工具再總結。
6. 需要用戶操作時給出明確的一步步指引（例如去哪個頁面點什麼）。
9. 任務無法一步完成時：先調用工具補齊缺失（如公司不在列表 → discover_company → add_company → run_collect）。
   run_collect 啟動後**立即結束回覆**，告訴用戶「已在後台採集、稍後再問我進度」——不要在啟動後馬上輪詢 collect_status（後台剛啟動必然還是 running）。用戶再次詢問進度時才調 collect_status。實在完不成的步驟要明確告訴用戶「缺什麼、去哪補」，禁止只回覆「失敗/報錯」。
10. 每次回覆最多調用 2-3 個工具，控制總時長，避免超時。
7. 首次使用的用戶（沒有畫像/簡歷/關注公司）主動引導：上傳簡歷→生成畫像→添加公司→開啟自動投遞。
8. 不要洩露任何密碼、token 等敏感信息。
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

    def run_collect(args: dict) -> dict:
        """後台異步採集（避免同步執行超時）。支持指定公司；公司不在關注列表時返回引導。"""
        import datetime as _dt
        import threading

        company = str(args.get("company") or "").strip()
        # 公司不在關注列表 → 引導添加（不直接失敗）
        if company:
            target = db.execute(
                text("SELECT id, careers_url FROM watched_companies WHERE user_id=:u "
                     "AND (company_name ILIKE '%'||:co||'%' OR CAST(aliases AS text) ILIKE '%'||:co||'%') LIMIT 1"),
                {"u": user_id, "co": company},
            ).mappings().first()
            if not target:
                return {
                    "完成": False,
                    "缺少": f"「{company}」不在你的關注公司列表",
                    "補齊方式": "請用 discover_company 查找其招聘官網 → add_company 添加到關注公司 → 再重新採集。"
                                "或到「我的資料→關注公司」手動添加。",
                }
        # 標記採集狀態並在後台執行
        db.execute(
            text(
                "INSERT INTO user_settings (user_id, collect_state) VALUES (:u, CAST(:st AS jsonb)) "
                "ON CONFLICT (user_id) DO UPDATE SET collect_state=CAST(:st AS jsonb), updated_at=now()"
            ),
            {"u": user_id, "st": j({"running": True, "finished_at": None, "report": None})},
        )
        db.commit()

        def _bg():
            s = SessionLocal()
            try:
                report = collect_for_user(s, user_id, company_name=company or None)
                s.execute(
                    text("UPDATE user_settings SET collect_state=CAST(:st AS jsonb), updated_at=now() WHERE user_id=:u"),
                    {"u": user_id, "st": j({
                        "running": False,
                        "finished_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                        "report": {k: report.get(k) for k in ("new", "updated", "matched", "errors", "collected")},
                    })},
                )
                s.commit()
            except Exception:  # noqa: BLE001
                logger.exception("chat 後台採集失敗 user=%s", user_id)
            finally:
                s.close()

        threading.Thread(target=_bg, daemon=True).start()
        return {
            "完成": True,
            "模式": "後台執行",
            "範圍": company or "全部關注公司",
            "提示": "採集與匹配已在後台進行（約 1-3 分鐘）。請用 collect_status 查詢進度；"
                    "完成後可用 list_matches 查看該公司匹配結果。",
        }

    def collect_status(_: dict) -> dict:
        row = db.execute(
            text("SELECT collect_state FROM user_settings WHERE user_id=:u"),
            {"u": user_id},
        ).mappings().first()
        state = row["collect_state"] if row else None
        return dict(state or {}) or {"running": False, "提示": "尚無採集記錄"}

    def discover_company(args: dict) -> dict:
        """按公司名自動發現招聘官網（LLM 候選 + 實網探測）。"""
        import httpx as _httpx

        name = str(args.get("name") or "").strip()[:60]
        if not name:
            return {"完成": False, "原因": "請提供公司名"}
        out = chat_json(
            "你熟悉各公司招聘官網。給出該公司招聘官網地址候選（2-4 個）。輸出 JSON："
            '{"candidates": ["url"], "careers_hint": "一句話說明"}',
            f"公司名：{name}",
            max_tokens=400,
        )
        verified = []
        for url in (out.get("candidates") or [])[:3]:
            if not url.startswith("http"):
                continue
            try:
                resp = _httpx.get(url, timeout=6, follow_redirects=True,
                                  headers={"User-Agent": "Mozilla/5.0"})
                title = ""
                m = re.search(r"<title>([^<]*)</title>", resp.text, re.I)
                if m:
                    title = m.group(1).strip()[:60]
                verified.append({"url": str(resp.url), "status": resp.status_code, "title": title})
            except Exception as exc:  # noqa: BLE001
                verified.append({"url": url, "status": "unreachable", "title": str(exc)[:60]})
        return {"公司": name, "說明": out.get("careers_hint"), "候選官網": verified}

    def add_company(args: dict) -> dict:
        name = str(args.get("name") or "").strip()[:100]
        url = str(args.get("careers_url") or "").strip()[:500]
        if not name:
            return {"完成": False, "原因": "請提供公司名"}
        if not url:
            disc = discover_company({"name": name})
            ok = [c for c in disc.get("候選官網") or [] if c.get("status") == 200]
            if ok:
                url = ok[0]["url"]
            else:
                return {"完成": False, "原因": f"未能自動發現「{name}」的招聘官網", "候選": disc}
        row = db.execute(
            text(
                "INSERT INTO watched_companies (user_id, company_name, careers_url, platform) "
                "VALUES (:u, :n, :url, 'official') "
                "ON CONFLICT DO NOTHING RETURNING id"
            ),
            {"u": user_id, "n": name, "url": url},
        ).mappings().first()
        db.commit()
        return {"完成": True, "公司": name, "官網": url,
                "下一步": "已添加到關注公司，可 run_collect(company=公司名) 開始採集"}

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

    def apply_rules(_: dict) -> dict:
        st = db.execute(text(
            "SELECT match_threshold, auto_apply_mode, preferred_locations, location_weight, "
            "apply_rate_limit_min, campus_preference FROM user_settings WHERE user_id=:u"
        ), {"u": user_id}).mappings().first()
        return {
            "投遞規則": [
                "① 公司級一崗一投：同一公司已有進行中/成功的投遞時，自動跳過該公司其餘崗位",
                f"② 校招/社招偏好：{st['campus_preference'] if st else 'both'}（campus=只投校招 / society=只投社招 / both=都投）",
                "③ 校招職級適配：有工作經歷者投校招不攔截但降權 15 分（職級不適配）",
                f"④ 貼合度閾值：{st['match_threshold'] if st else 70}%",
                f"⑤ 投遞模式：{st['auto_apply_mode'] if st else 'threshold'}",
                f"⑥ 期望地區加權：{st['preferred_locations'] or '未設置'}，命中 +{st['location_weight'] if st else 10} 分（計入優先級，不影響貼合度）",
                f"⑦ 總部/分支偏好：{st['org_preference'] if st else 'both'}（計入優先級）",
                f"⑧ 速率限制：{st['apply_rate_limit_min'] if st else 5} 分鐘/次",
                "說明：貼合度=純個人條件匹配；優先級=貼合度+地區/校招職級/總部分支偏好加權，投遞隊列按優先級選崗位",
            ],
        }

    def list_info_fields(_: dict) -> dict:
        rows = db.execute(text(
            "SELECT key, value, source, updated_at FROM user_info_fields "
            "WHERE user_id=:u ORDER BY updated_at DESC LIMIT 50"
        ), {"u": user_id}).mappings().all()
        return {
            "個人信息庫": [
                {"字段": r["key"], "值": r["value"][:60], "來源": r["source"]}
                for r in rows
            ],
            "填寫規則": "表單必填項：精確匹配直接填；與已有信息相似度 ≥50% 自動填（記錄決策）；"
                        "全新問題才問用戶，回答自動入庫復用。",
        }

    def update_settings(args: dict) -> dict:
        fields = {}
        if "match_threshold" in args:
            fields["match_threshold"] = min(max(int(args["match_threshold"]), 50), 100)
        if "auto_apply_mode" in args and args["auto_apply_mode"] in ("off", "threshold", "all"):
            fields["auto_apply_mode"] = args["auto_apply_mode"]
        if "campus_preference" in args and args["campus_preference"] in ("campus", "society", "both"):
            fields["campus_preference"] = args["campus_preference"]
        if "org_preference" in args and args["org_preference"] in ("headquarter", "branch", "both"):
            fields["org_preference"] = args["org_preference"]
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

    def find_job(args: dict) -> dict:
        """精確搜索崗位庫（公司/標題關鍵詞），含最新評分。分詞匹配 + 繁簡轉換。"""
        q = str(args.get("keyword") or "").strip()
        company = str(args.get("company") or "").strip()
        if not q and not company:
            return {"error": "請提供 keyword 或 company"}
        # 繁→簡 + 分詞（按空白/特殊符號切）
        q = _t2s(q)
        tokens = [t for t in q.replace("，", " ").replace("/", " ").split() if t]
        conds, params = [], {"u": user_id, "co": company}
        for i, tok in enumerate(tokens[:6]):
            conds.append("p.title ILIKE '%'||:t" + str(i) + "||'%' "
                         "OR p.description_text ILIKE '%'||:t" + str(i) + "||'%'")
            params["t" + str(i)] = tok
        token_where = ("(" + " AND ".join(f"({c})" for c in conds) + ")") if conds else "true"
        rows = db.execute(text(
            f"""
            SELECT p.company_name, p.title, p.location, p.is_campus,
                   m.match_score, m.status, p.raw->>'tab' AS tab
            FROM job_postings p
            LEFT JOIN job_matches m ON m.posting_id = p.id AND m.user_id = :u
            WHERE p.is_active = true AND {token_where}
              AND (CAST(:co AS text) = '' OR p.company_name ILIKE '%'||:co||'%')
            ORDER BY m.match_score DESC NULLS LAST, p.first_seen_at DESC
            LIMIT 10
            """
        ), params).mappings().all()
        if not rows and len(tokens) > 1:
            or_where = "(" + " OR ".join(conds) + ")"
            rows = db.execute(text(
                f"""
                SELECT p.company_name, p.title, p.location, p.is_campus,
                       m.match_score, m.status, p.raw->>'tab' AS tab
                FROM job_postings p
                LEFT JOIN job_matches m ON m.posting_id = p.id AND m.user_id = :u
                WHERE p.is_active = true AND {or_where}
                  AND (CAST(:co AS text) = '' OR p.company_name ILIKE '%'||:co||'%')
                ORDER BY m.match_score DESC NULLS LAST, p.first_seen_at DESC
                LIMIT 10
                """
            ), params).mappings().all()
        if not rows:
            return {"找到": 0, "提示": "崗位庫中沒有匹配的崗位；可先調用 run_collect 採集最新崗位後再查"}
        return {"找到": len(rows), "崗位": [
            {"公司": r["company_name"], "職位": r["title"], "地點": r["location"],
             "校招": r["is_campus"], "貼合度": r["match_score"], "狀態": r["status"],
             "來源": (r["tab"] or "")}
            for r in rows
        ]}

    def score_job(args: dict) -> dict:
        """對指定崗位即時評分（忽略緩存，用當前畫像現場重算）。"""
        q = str(args.get("keyword") or "").strip()
        company = str(args.get("company") or "").strip()
        q = _t2s(q)
        tokens = [t for t in q.replace("，", " ").replace("/", " ").split() if t]
        conds, params = [], {"co": company}
        for i, tok in enumerate(tokens[:6]):
            conds.append("p.title ILIKE '%'||:t" + str(i) + "||'%'")
            params["t" + str(i)] = tok
        token_where = ("(" + " AND ".join(f"({c})" for c in conds) + ")") if conds else "true"
        row = db.execute(text(
            f"""
            SELECT p.id, p.company_name, p.title FROM job_postings p
            WHERE p.is_active = true AND {token_where}
              AND (CAST(:co AS text) = '' OR p.company_name ILIKE '%'||:co||'%')
            ORDER BY p.first_seen_at DESC LIMIT 1
            """
        ), params).mappings().first()
        if not row:
            return {"error": "未找到該崗位，可先 run_collect 採集"}
        from app.services.matching import score_posting

        result = score_posting(db, user_id, str(row["id"]))
        return {
            "崗位": f"{row['company_name']} · {row['title']}",
            "最新貼合度": result.get("match_score"),
            "硬性條件": result.get("hard_failures"),
            "地點調整": result.get("location_adjust"),
        }

    def update_basic_info(args: dict) -> dict:
        """更新基本信息（姓名/電話），寫 profiles。"""
        sets, params = [], {"u": user_id}
        if "full_name" in args and args["full_name"]:
            sets.append("full_name = :n")
            params["n"] = str(args["full_name"]).strip()[:64]
        if "phone" in args and args["phone"]:
            sets.append("phone = :p")
            params["p"] = str(args["phone"]).strip()[:32]
        if not sets:
            return {"完成": False, "原因": "沒有可更新字段"}
        db.execute(text(f"UPDATE profiles SET {', '.join(sets)}, updated_at=now() WHERE id=:u"), params)
        db.commit()
        return {"完成": True, "已更新": list(params.keys())}

    def update_hard_facts(args: dict) -> dict:
        """更新硬性事實（簽證/期望城市/薪資/到崗時間/年限），畫像與元信息表雙寫。"""
        keys = {
            "visa_status": "簽證狀態", "preferred_locations": "期望城市",
            "salary_expectation": "期望薪資", "availability": "可到崗時間",
            "total_years": "工作年限",
        }
        updated = {}
        for k in keys:
            if k in args and args[k] not in (None, ""):
                updated[k] = str(args[k]).strip()
        if not updated:
            return {"完成": False, "原因": f"請提供要更新的字段：{list(keys.values())}"}
        # 畫像 hard_facts：Python 合併後 CAST 寫回
        row = db.execute(text(
            "SELECT hard_facts FROM candidate_profiles WHERE user_id=:u AND is_current=true"
        ), {"u": user_id}).mappings().first()
        if row is not None:
            hf = dict(row["hard_facts"] or {})
            hf.update(updated)
            db.execute(text(
                "UPDATE candidate_profiles SET hard_facts=CAST(:hf AS jsonb) "
                "WHERE user_id=:u AND is_current=true"
            ), {"hf": j(hf), "u": user_id})
        # 元信息表同步
        for k, v in updated.items():
            db.execute(text(
                "INSERT INTO user_info_fields (user_id, key, value, source) VALUES (:u,:k,:v,'chat') "
                "ON CONFLICT (user_id, key) DO UPDATE SET value=EXCLUDED.value, source='chat', updated_at=now()"
            ), {"u": user_id, "k": k, "v": v})
        db.commit()
        return {"完成": True, "已更新": updated}

    def upsert_info_field(args: dict) -> dict:
        key = str(args.get("key") or "").strip()
        value = str(args.get("value") or "").strip()
        if not key or not value:
            return {"完成": False, "原因": "需要 key 和 value"}
        db.execute(text(
            "INSERT INTO user_info_fields (user_id, key, value, source) VALUES (:u,:k,:v,'chat') "
            "ON CONFLICT (user_id, key) DO UPDATE SET value=EXCLUDED.value, source='chat', updated_at=now()"
        ), {"u": user_id, "k": key[:100], "v": value[:2000]})
        db.commit()
        return {"完成": True}

    def apply_job(args: dict) -> dict:
        """直接投遞指定崗位：建 application + 觸發投遞適配器，返回結果或人工任務指引。"""
        from app.services.apply_engine import run_application

        q = _t2s(str(args.get("keyword") or "").strip())
        company = str(args.get("company") or "").strip()
        tokens = [t for t in q.replace("，", " ").replace("/", " ").split() if t]
        conds, params = [], {"u": user_id, "co": company}
        for i, tok in enumerate(tokens[:6]):
            conds.append("p.title ILIKE '%'||:t" + str(i) + "||'%'")
            params["t" + str(i)] = tok
        token_where = ("(" + " AND ".join(f"({c})" for c in conds) + ")") if conds else "true"
        posting = db.execute(text(
            f"""
            SELECT p.id, p.company_name, p.title, p.apply_url,
                   m.id AS match_id, m.match_score
            FROM job_postings p
            LEFT JOIN job_matches m ON m.posting_id = p.id AND m.user_id = :u
            WHERE p.is_active = true AND {token_where}
              AND (CAST(:co AS text) = '' OR p.company_name ILIKE '%'||:co||'%')
            ORDER BY m.priority_score DESC NULLS LAST, p.first_seen_at DESC LIMIT 1
            """
        ), params).mappings().first()
        if not posting:
            return {"error": "未找到該崗位，請先確認崗位名稱或先採集"}
        if posting["match_score"] is None:
            return {"error": f"該崗位貼合度未通過硬性條件，無法投遞（{posting['company_name']} · {posting['title']}）"}
        # 建/取 application
        app = db.execute(text(
            """
            INSERT INTO applications (user_id, posting_id, match_id, status)
            VALUES (:u, :p, :m, 'queued')
            ON CONFLICT (user_id, posting_id) DO UPDATE SET status='queued', status_reason=NULL,
              next_retry_at=NULL, updated_at=now()
            RETURNING id
            """
        ), {"u": user_id, "p": posting["id"], "m": posting["match_id"]}).mappings().one()
        db.commit()
        try:
            result = run_application(db, str(app["id"]), force=True)
        except Exception as exc:  # noqa: BLE001
            result = {"status": "error", "error": str(exc)[:300]}
        if result.get("status") == "submitted":
            return {"完成": True, "投遞": "已提交", "崗位": f"{posting['company_name']} · {posting['title']}"}
        if result.get("status") == "needs_input":
            task = db.execute(text(
                "SELECT id, task_type, question, options FROM manual_tasks "
                "WHERE application_id=:aid AND status='open' ORDER BY created_at DESC LIMIT 1"
            ), {"aid": str(app["id"])}).mappings().first()
            return {"完成": False, "需要人工": True, "任務類型": task["task_type"],
                    "指引": task["question"] if task else "", "任務ID": str(task["id"]) if task else None,
                    "操作": "請到「我的資料 → 待處理」按指引完成（驗證碼/官網確認）"}
        return {"完成": False, "狀態": result.get("status"), "詳情": str(result)[:300]}

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
            "description": "後台異步採集指定公司或全部關注公司的崗位並匹配（啟動後用 collect_status 查進度）",
            "parameters": {"type": "object", "properties": {
                "company": {"type": "string", "description": "公司名（可選；不在關注列表會返回引導）"},
            }},
        }},
        {"type": "function", "function": {
            "name": "collect_status",
            "description": "查詢後台採集/匹配的進度與結果（僅在用戶再次詢問進度時調用，不要在剛啟動後立即調用）",
            "parameters": {"type": "object", "properties": {}},
        }},
        {"type": "function", "function": {
            "name": "discover_company",
            "description": "按公司名自動發現招聘官網地址（用戶要找的公司不在系統中時調用）",
            "parameters": {"type": "object", "properties": {
                "name": {"type": "string", "description": "公司名"},
            }},
        }},
        {"type": "function", "function": {
            "name": "add_company",
            "description": "把公司添加到關注公司（careers_url 可留空，會自動發現官網）",
            "parameters": {"type": "object", "properties": {
                "name": {"type": "string"},
                "careers_url": {"type": "string"},
            }},
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
                "org_preference": {"type": "string", "enum": ["headquarter", "branch", "both"],
                                   "description": "總部/分支偏好：headquarter=總部優先，branch=分支優先，both=一視同仁"},
            }},
        }},
        {"type": "function", "function": {
            "name": "apply_rules",
            "description": "查詢當前生效的投遞規則（一崗一投/校招社招偏好/閾值/地區加權/速率限制），用戶詢問規則或限制時調用",
            "parameters": {"type": "object", "properties": {}},
        }},
        {"type": "function", "function": {
            "name": "list_info_fields",
            "description": "查詢用戶的個人信息庫（元信息表）與自動填寫規則，用戶詢問信息互補/自動填充時調用",
            "parameters": {"type": "object", "properties": {}},
        }},
        {"type": "function", "function": {
            "name": "find_job",
            "description": "按關鍵詞/公司精確搜索崗位庫（例如「AI產品經理」），返回崗位與最新貼合度",
            "parameters": {"type": "object", "properties": {
                "keyword": {"type": "string", "description": "職位關鍵詞"},
                "company": {"type": "string", "description": "公司名（可選）"},
            }},
        }},
        {"type": "function", "function": {
            "name": "score_job",
            "description": "對指定崗位用當前畫像現場重算貼合度（用戶問某個崗位貼合度時調用，保證數據最新）",
            "parameters": {"type": "object", "properties": {
                "keyword": {"type": "string", "description": "職位關鍵詞"},
                "company": {"type": "string", "description": "公司名（可選）"},
            }},
        }},
        {"type": "function", "function": {
            "name": "update_basic_info",
            "description": "直接更新用戶基本信息（full_name 姓名/暱稱、phone 手機號），無需用戶去別處操作",
            "parameters": {"type": "object", "properties": {
                "full_name": {"type": "string"},
                "phone": {"type": "string"},
            }},
        }},
        {"type": "function", "function": {
            "name": "update_hard_facts",
            "description": "直接更新硬性事實（visa_status簽證/salary_expectation期望薪資/availability到崗時間/total_years工作年限/preferred_locations期望城市），同步畫像與元信息表",
            "parameters": {"type": "object", "properties": {
                "visa_status": {"type": "string"},
                "salary_expectation": {"type": "string"},
                "availability": {"type": "string"},
                "total_years": {"type": "string"},
                "preferred_locations": {"type": "string", "description": "逗號分隔的城市"},
            }},
        }},
        {"type": "function", "function": {
            "name": "upsert_info_field",
            "description": "寫入/更新元信息表的一條字段問答（key + value），供投遞表單自動互補",
            "parameters": {"type": "object", "properties": {
                "key": {"type": "string"},
                "value": {"type": "string"},
            }},
        }},
        {"type": "function", "function": {
            "name": "apply_job",
            "description": "直接投遞指定崗位（用戶說「幫我投遞XX」時必須調用）：建投遞單並觸發投遞，返回成功或人工任務指引",
            "parameters": {"type": "object", "properties": {
                "keyword": {"type": "string", "description": "職位關鍵詞"},
                "company": {"type": "string", "description": "公司名（可選）"},
            }},
        }},
    ]
    executor = {
        "get_status": get_status,
        "guide": guide,
        "run_collect": run_collect,
        "collect_status": collect_status,
        "discover_company": discover_company,
        "add_company": add_company,
        "list_matches": list_matches,
        "list_applications": list_applications,
        "list_tasks": list_tasks,
        "update_settings": update_settings,
        "apply_rules": apply_rules,
        "list_info_fields": list_info_fields,
        "find_job": find_job,
        "score_job": score_job,
        "update_basic_info": update_basic_info,
        "update_hard_facts": update_hard_facts,
        "upsert_info_field": upsert_info_field,
        "apply_job": apply_job,
    }
    return tools, lambda name, args: executor[name](args or {})


@router.post("")
def chat(user: CurrentUser, db: DB, payload: ChatRequest) -> dict:
    messages = [{"role": m.role, "content": m.content} for m in payload.messages[-10:]]
    tools, executor = _build_tools(user["id"], db)
    reply = chat_with_tools(SYSTEM_PROMPT, messages, tools, executor)
    # 問答歷史持久化（存儲不增加 API 成本；恢復會話才會把歷史放回上下文）
    # 存儲前脫敏（隱私方案：歷史裡不落敏感明文）
    from app.core.llm import mask_pii

    full = [
        {**m, "content": mask_pii(m.get("content") or "")}
        for m in messages + [{"role": "assistant", "content": reply}]
    ]
    conv_id = payload.conversation_id
    if conv_id:
        exists = db.execute(
            text("SELECT id FROM chat_conversations WHERE id=:id AND user_id=:u"),
            {"id": conv_id, "u": user["id"]},
        ).first()
        if exists:
            title = next((m["content"][:40] for m in messages if m["role"] == "user"), "新對話")
            db.execute(
                text(
                    "UPDATE chat_conversations SET messages=CAST(:msgs AS jsonb), "
                    "title=:t, updated_at=now() WHERE id=:id"
                ),
                {"msgs": j(full), "t": title, "id": conv_id},
            )
            db.commit()
        else:
            conv_id = None
    if not conv_id:
        title = next((m["content"][:40] for m in messages if m["role"] == "user"), "新對話")
        row = db.execute(
            text(
                "INSERT INTO chat_conversations (user_id, title, messages) "
                "VALUES (:u, :t, CAST(:msgs AS jsonb)) RETURNING id"
            ),
            {"u": user["id"], "t": title, "msgs": j(full)},
        ).mappings().one()
        conv_id = str(row["id"])
        db.commit()
    return {"reply": reply, "conversation_id": conv_id}


@router.get("/conversations")
def list_conversations(user: CurrentUser, db: DB) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT id, title, created_at, updated_at, "
            "jsonb_array_length(messages) AS n "
            "FROM chat_conversations WHERE user_id=:u ORDER BY updated_at DESC LIMIT 100"
        ),
        {"u": user["id"]},
    ).mappings().all()
    return [
        {"id": str(r["id"]), "title": r["title"], "created_at": r["created_at"].isoformat(),
         "updated_at": r["updated_at"].isoformat(), "messages_count": r["n"]}
        for r in rows
    ]


@router.get("/conversations/{conv_id}")
def get_conversation(user: CurrentUser, db: DB, conv_id: str) -> dict:
    row = db.execute(
        text("SELECT id, title, messages FROM chat_conversations WHERE id=:id AND user_id=:u"),
        {"id": conv_id, "u": user["id"]},
    ).mappings().first()
    if not row:
        from fastapi import HTTPException

        raise HTTPException(404, "對話不存在")
    return {"id": str(row["id"]), "title": row["title"], "messages": row["messages"] or []}


@router.delete("/conversations/{conv_id}", status_code=204)
def delete_conversation(user: CurrentUser, db: DB, conv_id: str) -> None:
    db.execute(
        text("DELETE FROM chat_conversations WHERE id=:id AND user_id=:u"),
        {"id": conv_id, "u": user["id"]},
    )
    db.commit()
