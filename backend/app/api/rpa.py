"""RPA 數據閉環：官網簡歷回傳 → 元信息 → 填報另一簡歷 → 一致性校驗。"""
from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.jsonutil import j, loads_json
from app.db import get_db

router = APIRouter(prefix="/rpa", tags=["rpa"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]

# 繁→簡（成對）
_T2S = str.maketrans(
    "產产品品經经理理開發发发經经验验數数據据應应屆届培培訓训員员務务職职證证聯联网网點点類类銀银資资讯讯質质動动範范組组织织級级實实习习業业專专门门間间時时机机構构規规畫画計计設设銷销場场營营錢钱術术歷历係系國国體体單单與与讀读種种長长風风控控優优權权廣广东东亞亚險险崗岗簡简選选擇择請请填填寫写郵邮箱箱畢毕學学戶户籍籍城城市市農农村村金金融融融練练續续處处號号灣湾滬沪深圳",
    "产品品经经理理开开发发发经经验验数数据据应应届届培培训训员业务务职职证证联联网网点点类类银银资资讯讯质质动动范范组组织织级级实实习习业业专专门门间间时时机机构构规规画画计计设设销销场场营营钱钱术术历历系系国国体体单单与与读读种种长长风风控控优优权权广广东东亚亚险险岗岗简简选选择择请请填填写写邮邮箱箱毕毕学学户户籍籍城城市市农农村村金金融融融练练续续处处号号湾湾沪沪深圳",
)


def _norm(label: str) -> str:
    """字段名標準化：繁→簡、去空白與標點。"""
    s = label.translate(_T2S)
    s = re.sub(r"[\s:：*＊·.。\-—_（）()【】\[\]]+", "", s)
    return s.lower()


class ScrapeRequest(BaseModel):
    site: str
    page_type: str
    fields: list[dict]  # [{label, value}]


@router.post("/scrape")
def scrape(user: CurrentUser, db: DB, payload: ScrapeRequest) -> dict:
    """官網簡歷回傳：字段寫入元信息表（敏感字段只存密文+掩碼）+ 存快照供校驗。"""
    from app.api.info_fields import SENSITIVE_KEY_RE, _mask_value

    fields = [f for f in payload.fields if (f.get("label") or "").strip() and str(f.get("value") or "").strip()]
    # 快照中的敏感值同樣打碼（快照不落明文）
    safe_fields = [
        {**f, "value": _mask_value(str(f["value"])) if SENSITIVE_KEY_RE.search(f.get("label", "")) else f["value"]}
        for f in fields
    ]
    db.execute(
        text(
            "INSERT INTO rpa_scrapes (user_id, site, page_type, data) "
            "VALUES (:u, :s, :pt, CAST(:d AS jsonb))"
        ),
        {"u": user["id"], "s": payload.site[:100], "pt": payload.page_type[:100],
         "d": j(safe_fields)},
    )
    for f in fields:
        key = f["label"].strip()[:100]
        value = str(f["value"]).strip()[:2000]
        sensitive = bool(SENSITIVE_KEY_RE.search(key))
        enc = f.get("encrypted") or None
        store_value = value if not sensitive else (_mask_value(value) if not enc else _mask_value(value))
        db.execute(
            text(
                "INSERT INTO user_info_fields (user_id, key, value, sensitive_enc, source) "
                "VALUES (:u,:k,:v,:enc,'website') "
                "ON CONFLICT (user_id, key) DO UPDATE SET value=EXCLUDED.value, "
                "sensitive_enc=COALESCE(EXCLUDED.sensitive_enc, user_info_fields.sensitive_enc), "
                "source='website', updated_at=now()"
            ),
            {"u": user["id"], "k": key, "v": store_value,
             "enc": (enc[:4000] if enc else None)},
        )
    db.commit()
    return {"ok": True, "saved": len(fields)}


@router.get("/fields")
def rpa_fields(user: CurrentUser, db: DB) -> list[dict]:
    """RPA 填報用：全部元信息字段（label+value+密文，密文由擴展本地解密）。"""
    rows = db.execute(
        text("SELECT key, value, sensitive_enc, source FROM user_info_fields WHERE user_id=:u ORDER BY updated_at DESC LIMIT 300"),
        {"u": user["id"]},
    ).mappings().all()
    return [{"label": r["key"], "value": r["value"], "source": r["source"],
             "encrypted": r["sensitive_enc"]} for r in rows]


class VerifyRequest(BaseModel):
    site: str
    page_type: str
    compare_with: str | None = None  # 例如「校園招聘簡歷」
    fields: list[dict]


@router.post("/verify")
def verify(user: CurrentUser, db: DB, payload: VerifyRequest) -> dict:
    """一致性校驗：當前抓取 vs 指定（或最近）快照。"""
    if payload.compare_with:
        snap = db.execute(
            text(
                "SELECT data FROM rpa_scrapes WHERE user_id=:u AND site=:s AND page_type=:pt "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"u": user["id"], "s": payload.site, "pt": payload.compare_with},
        ).mappings().first()
    else:
        snap = db.execute(
            text(
                "SELECT data FROM rpa_scrapes WHERE user_id=:u AND site=:s AND page_type != :pt "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"u": user["id"], "s": payload.site, "pt": payload.page_type},
        ).mappings().first()
    if not snap:
        return {"ok": False, "error": "沒有可對比的歷史快照（請先回傳一份簡歷）"}
    from app.api.info_fields import SENSITIVE_KEY_RE, _mask_value

    base = {_norm(f["label"]): str(f["value"]).strip() for f in (loads_json(snap["data"]) if isinstance(snap["data"], str) else snap["data"])}
    cur = {
        _norm(f["label"]): (
            _mask_value(str(f["value"]).strip())
            if SENSITIVE_KEY_RE.search(f.get("label", "")) else str(f["value"]).strip()
        )
        for f in payload.fields if f.get("label")
    }
    same, diff, missing = [], [], []
    for k, v in base.items():
        if k in cur:
            if cur[k] == v:
                same.append(k)
            else:
                diff.append({"label": k, "base": v, "current": cur[k]})
        else:
            missing.append({"label": k, "base": v})
    return {
        "ok": True,
        "total": len(base),
        "一致": len(same),
        "不一致": diff,
        "缺失": missing,
        "summary": f"共 {len(base)} 項：一致 {len(same)}、不一致 {len(diff)}、當前缺失 {len(missing)}",
    }


# ── 站點投遞流程知識（智能判斷：投遞前需要先維護哪些簡歷）──
SITE_FLOWS = {
    "citics": {
        "說明": "中信證券需先在「我的申請」維護對應簡歷，之後申請崗位無需再填個人信息。",
        "resume_by_tab": {
            "校園招聘·總部": "校園招聘簡歷",
            "校園招聘·分支機構": "分支校園招聘簡歷",
            "社會招聘·總部": "社會招聘簡歷",
            "社會招聘·分支機構": "分支社會招聘簡歷",
        },
    },
}


@router.get("/flow/{site}")
def site_flow(user: CurrentUser, site: str) -> dict:
    return SITE_FLOWS.get(site, {"說明": "通用流程：登錄後直接填表申請。"})


def required_resume_for(site: str, tab: str) -> str | None:
    flow = SITE_FLOWS.get(site, {})
    mapping = flow.get("resume_by_tab", {})
    return mapping.get(tab)
