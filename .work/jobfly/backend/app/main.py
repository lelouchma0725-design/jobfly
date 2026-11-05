"""FastAPI 應用入口。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    accounts, admin, applications, auth, chat, companies, documents, info_fields,
    jobs, matches, me, profile, tasks,
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


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
