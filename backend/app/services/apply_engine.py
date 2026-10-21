"""投遞引擎（FR-3b/3c）：狀態機、預檢、文檔準備、適配器調度、重試、人工接管、結果通知。

狀態流轉（對應《01-架構設計》4.3）：
queued → in_progress → submitted / needs_input(→answered→queued) / failed_retryable / aborted
"""
from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.apply import base as apply_base
from app.config import settings as app_settings
from app.core.audit import log_audit
from app.core.jsonutil import j
from app.services.form_mapping import build_candidate_payload, missing_fields
from app.api.info_fields import save_answer
from app.services.notifier import notify_with_fallback
from app.services.optimize import (
    attach_cover_letter,
    generate_cover_letter,
    optimize_resume_for_jd,
)
from app.services.parsing import download_bytes

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BASE_MINUTES = 30
QUEUE_LIMIT = 50  # 每輪 process_queue 處理上限（免費層資源控制）

# 人工回填允許覆蓋的字段白名單（防止注入任意鍵）
ANSWER_WHITELIST = {
    "full_name", "email", "phone", "location", "visa_status", "availability",
    "salary_expectation", "linkedin_url", "portfolio_url", "sms_code",
}


# ── 1. 隊列生成（FR-1g 三態策略）─────────────────────────────────────────

def create_applications_from_matches(db: Session, user_id: str) -> dict:
    st = db.execute(
        text(
            "SELECT auto_apply_mode, match_threshold, campus_preference "
            "FROM user_settings WHERE user_id=:uid"
        ),
        {"uid": user_id},
    ).mappings().first()
    mode = st["auto_apply_mode"] if st else "threshold"
    if mode == "off":
        return {"mode": "off", "created": 0}
    threshold = st["match_threshold"] if st else 70
    pref = (st["campus_preference"] if st else "both") or "both"
    where = "m.status IN ('new','pushed') AND m.match_score IS NOT NULL"
    params: dict = {"uid": user_id}
    if mode == "threshold":
        where += " AND m.match_score >= :th"
        params["th"] = threshold
    campus_where = ""
    if pref == "society":
        campus_where = "AND p.is_campus = false AND p.is_intern = false"
    elif pref == "campus":
        campus_where = "AND (p.is_campus = true OR p.is_intern = true)"
    result = db.execute(
        text(
            f"""
            INSERT INTO applications (user_id, posting_id, match_id, status)
            SELECT m.user_id, m.posting_id, m.id, 'queued'
            FROM job_matches m JOIN job_postings p ON p.id = m.posting_id
            WHERE m.user_id = :uid AND {where} AND p.is_active = true
              {campus_where}
              -- 公司級一崗一投：同一公司已有未終止投遞時跳過其餘崗位
              AND NOT EXISTS (
                SELECT 1 FROM applications a2
                JOIN job_postings p2 ON p2.id = a2.posting_id
                WHERE a2.user_id = :uid AND p2.company_name = p.company_name
                  AND a2.status NOT IN ('aborted', 'duplicate_skip', 'not_supported')
              )
            ORDER BY m.priority_score DESC NULLS LAST, m.match_score DESC NULLS LAST
            ON CONFLICT (user_id, posting_id) DO NOTHING
            """
        ),
        params,
    )
    db.execute(
        text(
            f"""
            UPDATE job_matches SET status='applying', updated_at=now()
            WHERE user_id = :uid AND status IN ('new','pushed')
              AND match_score IS NOT NULL
              {("AND match_score >= :th") if mode == 'threshold' else ''}
            """
        ),
        params,
    )
    db.commit()
    return {"mode": mode, "created": result.rowcount}


# ── 2. 預檢 ──────────────────────────────────────────────────────────────

def _preflight(payload: dict) -> dict | None:
    """返回阻塞原因（manual request 描述），無阻塞返回 None。"""
    miss = missing_fields(payload)
    if miss["critical"]:
        return {
            "task_type": "missing_field",
            "question": f"投遞前缺關鍵信息：{', '.join(miss['critical'])}。請補全後重試。",
            "options": {f: {"label": f, "type": "text"} for f in miss["critical"]},
        }
    if not payload.get("resume_file"):
        return {
            "task_type": "missing_file",
            "question": "尚未上傳可用簡歷（需上傳並解析成功）。請先在「我的文件」上傳簡歷。",
            "options": {"confirmed": {"label": "我已上傳簡歷", "type": "checkbox"}},
        }
    return None


# ── 3. 上下文準備（簡歷版本選擇 + AI 微調 + CL + 本地文件）──────────────

# 判斷需要英文簡歷的地點/地區關鍵詞（中國大陸以外）
_EN_HINTS = (
    "hong kong", "香港", "singapore", "london", "new york", "san francisco",
    "tokyo", "seoul", "sydney", "toronto", "vancouver", "remote", "海外",
    "united states", "united kingdom", "canada", "australia",
)


def _pick_resume_lang(app: dict) -> str:
    """根據崗位地點/公司選擇簡歷語言：海外/香港 → en，否則 zh。"""
    location = (app.get("location") or "").lower()
    text = f"{location} {(app.get('description_text') or '')[:300]}".lower()
    return "en" if any(h in text for h in _EN_HINTS) else "zh"


def _prepare_context(db: Session, app: dict, payload: dict, settings_row: dict) -> apply_base.ApplyContext:
    want_lang = _pick_resume_lang(app)
    version = db.execute(
        text(
            "SELECT id, content_md FROM resume_versions WHERE user_id=:uid "
            "AND content_md IS NOT NULL AND COALESCE(lang,'zh')=:lang "
            "ORDER BY version_no DESC LIMIT 1"
        ),
        {"uid": app["user_id"], "lang": want_lang},
    ).mappings().first()
    if not version:
        # 沒有對應語言的簡歷時回退到最新任意版本
        version = db.execute(
            text(
                "SELECT id, content_md FROM resume_versions WHERE user_id=:uid "
                "AND content_md IS NOT NULL ORDER BY version_no DESC LIMIT 1"
            ),
            {"uid": app["user_id"]},
        ).mappings().first()
    if not version:
        raise RuntimeError("沒有可用的簡歷文本（請先解析簡歷）")
    version_id, resume_text = str(version["id"]), version["content_md"]

    jd = app.get("description_text")
    if settings_row.get("ai_optimize_resume") and jd:
        new_vid = optimize_resume_for_jd(db, app["user_id"], version_id, jd)
        if new_vid:
            new_row = db.execute(
                text("SELECT content_md FROM resume_versions WHERE id=:id"),
                {"id": new_vid},
            ).mappings().first()
            version_id, resume_text = new_vid, new_row["content_md"]
            db.execute(
                text("UPDATE applications SET resume_version_id=:rv, updated_at=now() WHERE id=:id"),
                {"rv": version_id, "id": app["id"]},
            )
            db.commit()

    cover_letter = None
    if settings_row.get("ai_optimize_cover_letter") and jd:
        cover_letter = generate_cover_letter(db, app["user_id"], resume_text, jd)
        if cover_letter:
            attach_cover_letter(db, version_id, cover_letter)

    local_path = _download_resume(payload)

    account = _load_account(db, app)

    return apply_base.ApplyContext(
        user_id=app["user_id"],
        application_id=app["id"],
        posting=app,
        payload=payload,
        resume_text=resume_text,
        cover_letter=cover_letter,
        resume_local_path=local_path,
        settings=settings_row,
        account=account,
    )


def _load_account(db: Session, app: dict) -> dict | None:
    """解密平台帳號（按投遞來源匹配：gtht 等官網登錄型投遞）。

    匹配規則：來源為 gtht 時 → 從「公司官網/gtht」帳號中按網址或標籤
    匹配國泰海通；否則按 platform=來源 → 回退第一個 official 帳號。
    返回 {id, login, password}。
    """
    from app.core.security import decrypt_field, decrypt_json, get_dek_for_user

    dek = None

    def _decrypt(row) -> dict | None:
        nonlocal dek
        try:
            if dek is None:
                dek = get_dek_for_user(db, app["user_id"])
            return {
                "id": str(row["id"]),
                "login": decrypt_field(dek, row["login_identifier_enc"]),
                "password": decrypt_field(dek, row["password_enc"]) or "",
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("平台帳號解密失敗 user=%s: %s", app["user_id"], exc)
            return None

    if app["source"] == "gtht":
        rows = db.execute(
            text(
                "SELECT id, platform, label, login_identifier_enc, password_enc, meta_enc "
                "FROM platform_accounts "
                "WHERE user_id=:uid AND status != 'locked' "
                "AND (platform IN ('gtht','official') "
                "     OR label ILIKE '%國泰%' OR label ILIKE '%国泰%' OR label ILIKE '%gtht%') "
                "ORDER BY created_at"
            ),
            {"uid": app["user_id"]},
        ).mappings().all()
        for row in rows:
            meta = {}
            if row["meta_enc"]:
                try:
                    if dek is None:
                        dek = get_dek_for_user(db, app["user_id"])
                    meta = decrypt_json(dek, row["meta_enc"])
                except Exception:  # noqa: BLE001
                    meta = {}
            website = str(meta.get("website") or "").lower()
            label = (row["label"] or "").lower()
            if (row["platform"] == "gtht" or "gtht" in website
                    or "國泰" in label or "国泰" in label or "gtht" in label):
                return _decrypt(row)

    if app["source"] == "citics":
        # 中信帳號存 platform='official'，按網址/標籤匹配（platform_name 枚舉無 citics）
        rows = db.execute(
            text(
                "SELECT id, platform, label, login_identifier_enc, password_enc, meta_enc "
                "FROM platform_accounts "
                "WHERE user_id=:uid AND status != 'locked' "
                "AND (label ILIKE '%中信%' OR label ILIKE '%citics%') "
                "ORDER BY created_at"
            ),
            {"uid": app["user_id"]},
        ).mappings().all()
        for row in rows:
            return _decrypt(row)

    # platform 需在枚舉內，否則枚舉非法值會中止事務
    valid_platforms = ("workday", "greenhouse", "lever", "successfactors", "icims",
                       "official", "liepin", "boss", "lagou", "zhilian", "job51",
                       "linkedin", "indeed", "gtht", "other")
    for platform in (app["source"], "official"):
        if platform not in valid_platforms:
            continue
        row = db.execute(
            text(
                "SELECT id, login_identifier_enc, password_enc FROM platform_accounts "
                "WHERE user_id=:uid AND platform=:p AND status != 'locked' "
                "ORDER BY created_at LIMIT 1"
            ),
            {"uid": app["user_id"], "p": platform},
        ).mappings().first()
        if row:
            return _decrypt(row)
    return None


def _download_resume(payload: dict) -> str | None:
    rf = payload.get("resume_file")
    if not rf:
        return None
    data = download_bytes(rf["storage_path"])
    ext = os.path.splitext(rf["name"])[1] or ".pdf"
    fd, path = tempfile.mkstemp(suffix=ext, prefix="jobfly_resume_")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


# ── 4. 主流程 ────────────────────────────────────────────────────────────

def run_application(db: Session, application_id: str, dry_run: bool = False, force: bool = False) -> dict:
    app = _load_application(db, application_id)
    if not app:
        return {"error": "application not found"}
    if app["status"] in ("submitted", "aborted", "not_supported", "duplicate_skip"):
        return {"skipped": app["status"]}
    if app["status"] == "in_progress":
        return {"skipped": "in_progress"}
    if app["status"] == "needs_input" and not force:
        return {"skipped": "needs_input"}

    attempt_id = db.execute(
        text(
            "INSERT INTO application_attempts (user_id, application_id, attempt_no, result) "
            "VALUES (:uid, :aid, :n, 'failed') RETURNING id"
        ),
        {"uid": app["user_id"], "aid": application_id, "n": app["attempts_count"] + 1},
    ).mappings().one()["id"]
    db.execute(
        text(
            "UPDATE applications SET status='in_progress', current_step='prepare', "
            "attempts_count=attempts_count+1, updated_at=now() WHERE id=:id"
        ),
        {"id": application_id},
    )
    db.commit()

    outcome: dict = {}
    local_path: str | None = None
    try:
        if not app.get("apply_url"):
            _finish(db, app, application_id, "not_supported", "該崗位無申請入口", attempt_id, "aborted")
            outcome = {"status": "not_supported"}
        else:
            payload = build_candidate_payload(db, app["user_id"])
            _merge_answers(db, application_id, payload)
            blocker = _preflight(payload)
            if blocker:
                outcome = _block(db, app, application_id, attempt_id, blocker)
            else:
                settings_row = db.execute(
                    text("SELECT * FROM user_settings WHERE user_id=:uid"),
                    {"uid": app["user_id"]},
                ).mappings().first()
                ctx = _prepare_context(db, app, payload, dict(settings_row) if settings_row else {})
                local_path = ctx.resume_local_path
                ctx.dry_run = dry_run
                adapter = apply_base.get_apply_adapter(app["source"])
                db.execute(
                    text("UPDATE applications SET current_step='applying', updated_at=now() WHERE id=:id"),
                    {"id": application_id},
                )
                db.commit()
                result = adapter.apply(ctx)
                outcome = _settle(db, app, application_id, attempt_id, result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("投遞執行異常 app=%s", application_id)
        try:
            db.rollback()  # 若事務已中止，先回滾再收尾（防 InFailedSqlTransaction 連鎖）
        except Exception:  # noqa: BLE001
            pass
        outcome = _finish(
            db, app, application_id,
            "failed_retryable" if app["attempts_count"] < MAX_RETRIES else "aborted",
            f"內部錯誤: {exc}", attempt_id, "failed", error_code="internal_error",
        )
    finally:
        db.execute(
            text("UPDATE application_attempts SET finished_at=now() WHERE id=:id AND finished_at IS NULL"),
            {"id": attempt_id},
        )
        if local_path:
            try:
                os.unlink(local_path)
            except OSError:  # pragma: no cover
                pass
        db.commit()
    return outcome


def _load_application(db: Session, application_id: str) -> dict | None:
    row = db.execute(
        text(
            """
            SELECT a.*, p.company_name, p.title, p.location, p.source, p.apply_url,
                   p.description_text, p.external_id AS posting_external_id
            FROM applications a JOIN job_postings p ON p.id = a.posting_id
            WHERE a.id = :id
            """
        ),
        {"id": application_id},
    ).mappings().first()
    if not row:
        return None
    d = dict(row)
    d["id"] = str(d["id"])
    d["user_id"] = str(d["user_id"])
    return d


def _block(db: Session, app: dict, application_id: str, attempt_id: str, blocker: dict) -> dict:
    task_id = _create_manual_task(db, app, application_id, blocker)
    _finish(db, app, application_id, "needs_input", blocker["question"], attempt_id,
            "manual_input_needed", error_code=blocker["task_type"])
    _notify_manual(db, app, blocker["question"], task_id)
    return {"status": "needs_input", "task_id": task_id}


def _settle(db: Session, app: dict, application_id: str, attempt_id: str,
            result: apply_base.ApplyResult) -> dict:
    if result.success:
        db.execute(
            text("UPDATE job_matches SET status='applied', updated_at=now() WHERE id=:mid"),
            {"mid": app["match_id"]},
        )
        _finish(db, app, application_id, "submitted",
                f"投遞成功 ref={result.external_ref or ''}", attempt_id, "success")
        _notify_result(db, app, success=True, detail=result.external_ref or "")
        return {"status": "submitted", "external_ref": result.external_ref}
    if result.manual:
        blocker = {
            "task_type": result.manual.task_type,
            "question": result.manual.question,
            "options": result.manual.options,
            "screenshot_path": result.manual.screenshot_path,
        }
        task_id = _create_manual_task(db, app, application_id, blocker)
        _finish(db, app, application_id, "needs_input", result.manual.question, attempt_id,
                "manual_input_needed", error_code=result.error_code or result.manual.task_type)
        _notify_manual(db, app, result.manual.question, task_id)
        return {"status": "needs_input", "task_id": task_id}
    # 可重試失敗
    if app["attempts_count"] < MAX_RETRIES:
        retry_at = datetime.now(timezone.utc) + timedelta(minutes=RETRY_BASE_MINUTES * app["attempts_count"])
        db.execute(
            text("UPDATE applications SET next_retry_at=:t WHERE id=:id"),
            {"t": retry_at, "id": application_id},
        )
        _finish(db, app, application_id, "failed_retryable",
                result.error_detail or result.error_code or "投遞失敗", attempt_id, "failed",
                error_code=result.error_code)
        return {"status": "failed_retryable", "error": result.error_detail}
    _finish(db, app, application_id, "aborted",
            result.error_detail or "多次重試仍失敗", attempt_id, "aborted", error_code=result.error_code)
    _notify_result(db, app, success=False, detail=result.error_detail or result.error_code or "")
    return {"status": "aborted", "error": result.error_detail}


def _merge_answers(db: Session, application_id: str, payload: dict) -> None:
    """把最近一次人工回填合併進投遞上下文（FR-3c 直接框 → 繼續投遞）。"""
    task = db.execute(
        text(
            "SELECT answer FROM manual_tasks WHERE application_id=:aid AND status='answered' "
            "ORDER BY answered_at DESC LIMIT 1"
        ),
        {"aid": application_id},
    ).mappings().first()
    if not task or not task["answer"]:
        return
    for key, value in task["answer"].items():
        if key == "confirmed" or value is None:
            continue
        if key == "values" and isinstance(value, str):
            for line in value.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    if k in payload and v.strip():
                        payload[k] = v.strip()
        elif isinstance(value, str) and value.strip() and key in ANSWER_WHITELIST:
            payload[key] = value.strip()


def _finish(db: Session, app: dict, application_id: str, status: str, reason: str,
            attempt_id: str, attempt_result: str, error_code: str | None = None) -> dict:
    db.execute(
        text(
            "UPDATE applications SET status=CAST(:st AS application_status), status_reason=:r, "
            "current_step=NULL, "
            "submitted_at=CASE WHEN :st='submitted' THEN now() ELSE submitted_at END, "
            "updated_at=now() WHERE id=:id"
        ),
        {"st": status, "r": reason[:2000], "id": application_id},
    )
    db.execute(
        text(
            "UPDATE application_attempts SET result=CAST(:r AS attempt_result), error_code=:ec "
            "WHERE id=:id"
        ),
        {"r": attempt_result, "ec": error_code, "id": attempt_id},
    )
    log_audit(db, app["user_id"], "application.status", "applications", application_id,
              {"status": status, "reason": reason[:300]})
    db.commit()
    return {"status": status}


def _create_manual_task(db: Session, app: dict, application_id: str, blocker: dict) -> str:
    task = db.execute(
        text(
            """
            INSERT INTO manual_tasks
              (user_id, application_id, task_type, question, options, screenshot_path,
               status, expires_at)
            VALUES (:uid, :aid, CAST(:tt AS task_type), :q, CAST(:opt AS jsonb), :shot, 'open', now() + interval '48 hours')
            RETURNING id
            """
        ),
        {
            "uid": app["user_id"], "aid": application_id, "tt": blocker["task_type"],
            "q": blocker["question"], "opt": j(blocker.get("options")),
            "shot": blocker.get("screenshot_path"),
        },
    ).mappings().one()
    db.commit()
    return str(task["id"])


# ── 5. 隊列處理（調度器/手動觸發）────────────────────────────────────────

def process_queue(db: Session, user_id: str | None = None, limit: int = QUEUE_LIMIT) -> dict:
    where = "status='queued' OR (status='failed_retryable' AND next_retry_at <= now())"
    params: dict = {"lim": limit}
    if user_id:
        where = f"({where}) AND user_id = :uid"
        params["uid"] = user_id
    rows = db.execute(
        text(
            f"SELECT id FROM applications WHERE {where} ORDER BY created_at LIMIT :lim"
        ),
        params,
    ).mappings().all()
    done = {"processed": 0, "submitted": 0, "needs_input": 0, "failed": 0, "skipped": 0}
    for r in rows:
        app_id = str(r["id"])
        if not _rate_ok(db, app_id):
            done["skipped"] += 1
            continue
        out = run_application(db, app_id)
        if out.get("skipped"):
            done["skipped"] += 1
            continue
        done["processed"] += 1
        if out.get("status") == "submitted":
            done["submitted"] += 1
        elif out.get("status") == "needs_input":
            done["needs_input"] += 1
        else:
            done["failed"] += 1
    return done


def _rate_ok(db: Session, application_id: str) -> bool:
    """每用戶投遞最小間隔（apply_rate_limit_min），防止風控與資源耗盡。"""
    row = db.execute(
        text(
            """
            SELECT s.apply_rate_limit_min AS rate,
                   (SELECT MAX(at2.started_at) FROM application_attempts at2
                    JOIN applications a2 ON a2.id = at2.application_id
                    WHERE a2.user_id = a.user_id) AS last
            FROM applications a JOIN user_settings s ON s.user_id = a.user_id
            WHERE a.id = :id
            """
        ),
        {"id": application_id},
    ).mappings().first()
    if not row:
        return True
    rate = row["rate"] or 5
    if not row["last"]:
        return True
    elapsed = (datetime.now(timezone.utc) - row["last"]).total_seconds() / 60
    if elapsed < rate:
        db.execute(
            text(
                "UPDATE applications SET next_retry_at=:t, updated_at=now() WHERE id=:id"
            ),
            {"t": row["last"] + timedelta(minutes=rate), "id": application_id},
        )
        db.commit()
        return False
    return True


# ── 6. 人工接管回填 ──────────────────────────────────────────────────────

def answer_and_resume(db: Session, task_id: str, user_id: str, answer: dict | None) -> dict:
    task = db.execute(
        text("SELECT * FROM manual_tasks WHERE id=:id AND user_id=:uid"),
        {"id": task_id, "uid": user_id},
    ).mappings().first()
    if not task:
        return {"error": "task not found"}
    if task["status"] != "open":
        return {"skipped": task["status"]}
    db.execute(
        text(
            "UPDATE manual_tasks SET status='answered', answered_at=now(), answer=CAST(:a AS jsonb) "
            "WHERE id=:id"
        ),
        {"id": task_id, "a": j(answer or {})},
    )
    # 回填答案自動存庫（元信息表），下次同類字段免問
    for key, value in (answer or {}).items():
        if key in ("confirmed",) or value in (None, ""):
            continue
        if isinstance(value, str) and value.strip():
            try:
                save_answer(db, user_id, key, value.strip())
            except Exception:  # noqa: BLE001
                logger.warning("元信息存庫失敗 %s=%s", key, value[:50])
    db.commit()
    # 適配器專屬人工回填（如中信：用戶官網自行提交後確認 → 直接標記已投遞）
    if task["task_type"] == "citics_manual":
        try:
            from app.apply.citics_apply import merge_manual_answer

            app_row = _load_application(db, str(task["application_id"]))
            payload = build_candidate_payload(db, user_id)
            _merge_answers(db, str(task["application_id"]), payload)
            ctx = _prepare_context(db, app_row, payload, {})
            merged = merge_manual_answer(ctx, answer or {})
            if merged.get("submitted"):
                db.execute(
                    text("SELECT id FROM application_attempts WHERE application_id=:aid ORDER BY created_at DESC LIMIT 1"),
                    {"aid": task["application_id"]},
                )
                attempt = db.execute(
                    text("SELECT id FROM application_attempts WHERE application_id=:aid ORDER BY created_at DESC LIMIT 1"),
                    {"aid": task["application_id"]},
                ).mappings().first()
                _finish(db, app_row, str(task["application_id"]), "submitted",
                        f"用戶在官網完成申請（人工確認）: {merged['external_ref']}",
                        str(attempt["id"]) if attempt else "",
                        "submitted")
                log_audit(db, user_id, "application.submitted", "applications",
                          str(task["application_id"]), {"mode": "manual_confirmed"})
                return {"task": "answered", "application": {"status": "submitted"}}
        except Exception:  # noqa: BLE001
            logger.exception("citics 人工回填處理失敗")
    # 回填內容注入投遞上下文：answer 中與 payload 同名字段直接覆蓋
    db.execute(
        text(
            "UPDATE applications SET status='queued', status_reason='人工補充完成，等待重新投遞', "
            "next_retry_at=NULL, updated_at=now() WHERE id=:aid"
        ),
        {"aid": task["application_id"]},
    )
    db.commit()
    out = run_application(db, str(task["application_id"]))
    return {"task": "answered", "application": out}


# ── 7. 通知 ──────────────────────────────────────────────────────────────

def _notify_result(db: Session, app: dict, success: bool, detail: str) -> None:
    title = f"{'✅ 投遞成功' if success else '❌ 投遞失敗'}: {app['company_name']} · {app['title']}"
    content = (
        f"**{app['company_name']} · {app['title']}**\n"
        f"{'已成功投遞' if success else '投遞失敗，已停止自動重試'}：{detail}\n"
        f"[查看投遞記錄]({app_settings.frontend_url}/applications)"
    )
    notify_with_fallback(db, app["user_id"], "apply_result", title, content,
                         meta={"application_id": app["id"]})


def _notify_manual(db: Session, app: dict, question: str, task_id: str) -> None:
    title = f"✋ 需要你處理: {app['company_name']} · {app['title']}"
    content = (
        f"**{app['company_name']} · {app['title']}** 的投遞被暫停：\n{question}\n\n"
        f"[點擊處理]({app_settings.frontend_url}/tasks)"
    )
    notify_with_fallback(db, app["user_id"], "manual_task", title, content,
                         meta={"task_id": task_id, "application_id": app["id"]})
