"""JSONB 參數助手：psycopg 無法直接適配 dict/list，需先序列化。"""
from __future__ import annotations

import json


def j(v) -> str | None:
    """把 Python 對象轉成可安全傳入 `CAST(:x AS jsonb)` 的 JSON 字符串。"""
    if v is None:
        return None
    return json.dumps(v, ensure_ascii=False)
