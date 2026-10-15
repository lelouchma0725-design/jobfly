"""AI 用戶畫像端點（FR-1e）。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
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


@router.post("/generate", status_code=201)
def generate(user: CurrentUser, db: DB, payload: GenerateRequest) -> dict:
    try:
        profile_id = generate_profile(db, user["id"], payload.resume_version_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"id": profile_id}


@router.get("")
def read_profile(user: CurrentUser, db: DB) -> dict:
    profile = get_current_profile(db, user["id"])
    if not profile:
        raise HTTPException(404, "尚未生成畫像：請先上傳並解析簡歷，然後點擊「生成畫像」")
    return profile
