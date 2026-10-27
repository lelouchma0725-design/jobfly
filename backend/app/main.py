"""FastAPI 應用入口。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    accounts, admin, applications, auth, chat, companies, documents, info_fields,
    jobs, matches, me, profile, rpa, tasks,
)
from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("jobfly")


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = settings.missing_critical()
    if missing:
        logger.warning(
            "缺少關鍵環境變量: %s —— /healthz 可用，但對應功能將在首次使用時報錯（參考 backend/.env.example）",
            ", ".join(missing),
        )
    logger.info("JobsComing backend starting (env=%s)", settings.app_env)
    if not missing:
        try:
            from app.core.scheduler import start_scheduler, stop_scheduler

            start_scheduler()
        except Exception:  # noqa: BLE001
            logger.exception("調度器啟動失敗（不影響 API 服務）")
    yield
    from app.core.scheduler import stop_scheduler

    stop_scheduler()
    logger.info("JobsComing backend stopped")


app = FastAPI(title="JobsComing API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(me.router, prefix="/api")
app.include_router(accounts.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(companies.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(matches.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(applications.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(info_fields.router, prefix="/api")
app.include_router(rpa.router, prefix="/api")


if settings.debug_500 == "1":
    import traceback

    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.exception_handler(Exception)
    async def _debug_500(request: Request, exc: Exception):
        logger.exception("未處理異常 %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc), "trace": traceback.format_exc()[-3000:]},
        )


@app.get("/healthz/full")
def healthz_full() -> dict:
    """詳細健康檢查：含 Playwright 可用性（供診斷投遞環境）。"""
    playwright_ok = False
    pw_err = ""
    try:
        import playwright  # noqa: F401

        playwright_ok = True
    except Exception as exc:  # noqa: BLE001
        pw_err = repr(exc)
    browsers = False
    try:
        from pathlib import Path

        browsers = Path("/ms-playwright").is_dir()
    except Exception:  # noqa: BLE001
        pass
    db_ok = False
    try:
        from sqlalchemy import text as _text

        from app.db import SessionLocal

        s = SessionLocal()
        try:
            s.execute(_text("SELECT 1"))
            db_ok = True
        finally:
            s.close()
    except Exception:  # noqa: BLE001
        pass
    return {"status": "ok", "playwright": playwright_ok, "playwright_err": pw_err,
            "browsers_dir": browsers, "db": db_ok}


@app.get("/healthz/feishu")
def healthz_feishu() -> dict:
    """診斷：從服務器側探測飛書門戶（驗證地域風控）。"""
    import httpx as _hx

    out = {}
    try:
        c = _hx.Client(headers={"User-Agent": "Mozilla/5.0"}, timeout=20, follow_redirects=True)
        r0 = c.get("https://gffunds.jobs.feishu.cn/833056")
        out["page"] = r0.status_code
        out["cookies"] = list(c.cookies.keys())
        csrf = c.cookies.get("atsx-csrf-token")
        out["csrf"] = bool(csrf)
        r = c.post("https://gffunds.jobs.feishu.cn/api/v1/search/job/posts",
                   headers={"Content-Type": "application/json", "Accept": "application/json",
                            "website-path": "833056", "portal-channel": "saas-career",
                            "portal-platform": "pc",
                            "x-csrf-token": (csrf or ""),
                            "Referer": "https://gffunds.jobs.feishu.cn/833056"},
                   json={"keyword": "", "limit": 5, "offset": 0, "job_category_id_list": [],
                         "tag_id_list": [], "location_code_list": [], "subject_id_list": [],
                         "recruitment_id_list": [], "portal_type": 6,
                         "job_function_id_list": [], "storefront_id_list": [],
                         "portal_entrance": 1})
        out["api"] = r.status_code
        if r.status_code == 200:
            d = r.json().get("data") or {}
            out["count"] = d.get("count")
        else:
            out["body"] = r.text[:120]
        c.close()
    except Exception as exc:  # noqa: BLE001
        out["error"] = repr(exc)[:200]
    return out


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
