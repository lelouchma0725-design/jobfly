"""AI 用戶畫像端點（FR-1e）。生成後自動觸發重新匹配。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db import get_db
from app.services.profile import generate_profile, get_current_profile

router = APIRouter(prefix="/profile", tags=["profile"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]


class GenerateRequest(BaseModel):
    resume_version_id: str | None = None


def _rematch_bg(user_id: str) -> None:
    """畫像更新後在後台用新畫像重新匹配歷史崗位。"""
    from app.api.matches import rematch_all_for_user
    from app.db import SessionLocal

    s = SessionLocal()
    try:
        rematch_all_for_user(s, user_id)
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception("畫像更新後重匹配失敗 user=%s", user_id)
    finally:
        s.close()


@router.post("/generate", status_code=201)
def generate(
    user: CurrentUser, db: DB, payload: GenerateRequest, background_tasks: BackgroundTasks
) -> dict:
    try:
        profile_id = generate_profile(db, user["id"], payload.resume_version_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    background_tasks.add_task(_rematch_bg, user["id"])
    return {"id": profile_id, "note": "畫像已更新，正在後台用新畫像重新匹配歷史崗位"}


@router.get("")
def read_profile(user: CurrentUser, db: DB) -> dict:
    profile = get_current_profile(db, user["id"])
    if not profile:
        raise HTTPException(404, "尚未生成畫像：請先上傳並解析簡歷，然後點擊「生成畫像」")
    return profile
