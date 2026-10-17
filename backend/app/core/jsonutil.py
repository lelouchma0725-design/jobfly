"""JSONB 參數助手：psycopg 無法直接適配 dict/list，需先序列化。"""
from __future__ import annotations

import json


def j(v) -> str | None:
    """把 Python 對象轉成可安全傳入 `CAST(:x AS jsonb)` 的 JSON 字符串。"""
    if v is None:
        return None
    return json.dumps(v, ensure_ascii=False)


def loads_json(v):
    """安全解析 JSON 字符串（jsonb 經 psycopg 可能以字符串返回）；失敗返回原值。"""
    if not isinstance(v, str):
        return v
    try:
        return json.loads(v)
    except (ValueError, TypeError):
        return v
