"""JD 詳情頁文本 → LLM 結構化抽取（公司/實際僱主/薪資/職責/獵頭/合同工）。"""
from __future__ import annotations

import logging

from app.core.llm import chat_json

logger = logging.getLogger(__name__)

EXTRACT_SYSTEM = """你是香港招聘網站職位詳情解析器。從頁面文本中抽取字段，輸出 JSON：
{"company": "發布職位的公司名", "actual_employer": "實際僱主（獵頭發布時為客戶公司；非獵頭發布時留空）",
 "is_headhunter": true|false,
 "salary": "薪資原文（含貨幣/月/年，如 HK$40,000-60,000/mo）",
 "location": "工作地點",
 "description": "崗位職責與要求（原文摘錄，最多 800 字）",
 "is_contract": true|false,
 "contract_note": "若 is_contract，註明合同期（如 6 個月）"}
規則：
- is_headhunter：頁面顯示的發布方是招聘中介/獵頭（如 Robert Walters、Michael Page、Adecco、Ambition、TEKsystems、Randstad、Oliver James、JFE、Newrecs、Crossings、Ikas 等），而 JD 描述的是其客戶公司的職位 → true，actual_employer 填 JD 中提到的實際僱主
- 發布方就是實際僱主 → is_headhunter=false，actual_employer 留空
- is_contract：含 contract/合約/合同/固定期限/fixed-term/12 months 等 → true
- 只輸出 JSON"""


def extract_detail(text: str, fallback_title: str = "") -> dict:
    """LLM 抽取詳情字段。失敗返回空 dict。"""
    try:
        out = chat_json(EXTRACT_SYSTEM, f"職位標題：{fallback_title}\n頁面文本：\n{text[:6000]}", max_tokens=800)
        return out if isinstance(out, dict) else {}
    except Exception:  # noqa: BLE001
        logger.exception("JD 詳情抽取失敗")
        return {}
