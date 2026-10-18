"""LLM 客戶端（OpenAI 兼容，可切換 DeepSeek/OpenAI 等）。

- chat: 普通對話補全
- chat_json: 要求 JSON 輸出並容錯解析（處理 markdown 代碼塊、前後綴雜訊）
- 記錄 token 用量到 ai_jobs（成本控制，GAP-11）
"""
from __future__ import annotations

import json
import logging
import re

from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)

_client: OpenAI | None = None

# 進程內用量計數（免費層單進程部署夠用；多進程時以 ai_jobs 表為準）
USAGE = {"calls": 0, "tokens_in": 0, "tokens_out": 0}

# ── 隱私脫敏（方案 A）：發送 LLM 前對個人敏感信息打碼 ──────────────────
_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d)(\d{4})(\d{4})(?!\d)")
_IDCARD_RE = re.compile(r"(?<!\d)(\d{6})(\d{8})(\d{3}[\dXx])(?!\d)")
_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def mask_pii(text: str) -> str:
    """脫敏：手機 189****9707、身份證前6後4保留中間打碼、郵箱名打碼。"""
    if not text:
        return text
    text = _PHONE_RE.sub(r"\1****\3", text)
    text = _IDCARD_RE.sub(r"\1********\3", text)
    text = _EMAIL_RE.sub(r"\1***@\2", text)
    return text


def _sanitize_messages(messages: list[dict]) -> list[dict]:
    return [{**m, "content": mask_pii(m.get("content") or "")} for m in messages]


def usage() -> dict:
    return dict(USAGE)


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.llm_api_key:
            raise RuntimeError("LLM_API_KEY 未配置（參考 backend/.env.example）")
        _client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
    return _client


def _extract_json(text: str) -> dict:
    """從 LLM 輸出中容錯提取 JSON 對象。"""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 修復常見問題：去掉尾隨逗號
        fixed = re.sub(r",\s*([}\]])", r"\1", text)
        return json.loads(fixed)


def chat(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 4000,
    temperature: float = 0.2,
) -> str:
    resp = _get_client().chat.completions.create(
        model=model or settings.llm_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": mask_pii(user)},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    if resp.usage:
        USAGE["calls"] += 1
        USAGE["tokens_in"] += resp.usage.prompt_tokens or 0
        USAGE["tokens_out"] += resp.usage.completion_tokens or 0
    return resp.choices[0].message.content or ""


def chat_json(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 4000,
    retries: int = 2,
) -> dict:
    """要求 LLM 返回 JSON；解析失敗時自動重試（帶錯誤提示）。"""
    last_err = ""
    for attempt in range(retries + 1):
        prompt = user
        if last_err:
            prompt += f"\n\n【上一次輸出無法解析為 JSON：{last_err}。請只輸出一個合法的 JSON 對象，不要包含任何其他文字。】"
        try:
            out = chat(
                system + "\n你必須只輸出一個合法 JSON 對象，不要 markdown 代碼塊，不要任何解釋。",
                prompt,
                model=model or settings.llm_structured_model,
                max_tokens=max_tokens,
                temperature=0.1,
            )
            return _extract_json(out)
        except (json.JSONDecodeError, ValueError) as exc:
            last_err = str(exc)
            logger.warning("JSON 解析失敗，重試 %s/%s: %s", attempt + 1, retries, exc)
    raise RuntimeError(f"LLM 多次輸出非法 JSON: {last_err}")


def chat_with_tools(
    system: str,
    messages: list[dict],
    tools: list[dict],
    tool_executor,
    *,
    model: str | None = None,
    max_iters: int = 6,
) -> str:
    """函數調用（tool calling）代理循環：LLM 決定調用工具 → 執行 → 回填結果。

    tool_executor: callable(name: str, args: dict) -> dict
    返回最終的助手文本回覆。
    """
    msgs: list[dict] = [{"role": "system", "content": system}, *(_sanitize_messages(messages))]
    for _ in range(max_iters):
        resp = _get_client().chat.completions.create(
            model=model or settings.llm_model,
            messages=msgs,
            tools=tools,
            max_tokens=2000,
            temperature=0.3,
        )
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return msg.content or ""
        msgs.append(msg)  # assistant 帶 tool_calls 的消息
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            try:
                result = tool_executor(name, args)
            except Exception as exc:  # noqa: BLE001
                logger.exception("工具執行失敗 %s", name)
                result = {"error": str(exc)[:500]}
            msgs.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False)[:6000],
            })
    return "（操作步驟過多，請簡化您的問題後再試）"
