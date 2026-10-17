"""SQLAlchemy 引擎與會話。

後端以 service_role / postgres 身份連接（RLS 對 postgres 不生效），
因此多租戶隔離在代碼層強制：所有用戶數據查詢必須過濾 user_id
（參見 app/core/auth.py 的 get_current_user 依賴注入）。

引擎惰性創建：未配置 DATABASE_URL 時應用仍可啟動（/healthz 可用），
首次真正訪問數據庫時才報錯。
"""
from __future__ import annotations

import json
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL 未配置（參考 backend/.env.example）")
        _engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            json_deserializer=json.loads,  # jsonb 字段自動返回 Python 對象（防 .get 崩潰）
        )
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def SessionLocal() -> Session:
    """惰性會話工廠（供調度器/測試等直接使用）。"""
    get_engine()
    return _SessionLocal()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
