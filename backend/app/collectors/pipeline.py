"""採集流水線：目標解析 → 適配器採集 → 入庫去重 → 下架標記 → 觸發匹配。

FR-3a2 每日定時採集的核心；manual trigger 與調度器都走這裡。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.collectors import base
from app.collectors.official import detect_platform
from app.services.matching import score_posting

logger = logging.getLogger(__name__)

STALE_AFTER_DAYS = 7          # 連續 N 天未出現 → 標記下架
MATCH_CAP_PER_USER = 20       # 每輪每用戶最多匹配的新崗位數（控制 LLM 成本）


def _health(db: Session, adapter: str, ok: bool, error: str | None, duration_ms: int) -> None:
    db.execute(
        text(
            """
            INSERT INTO adapter_health
              (adapter, last_run_at, last_success_at, success_count, fail_count, last_error, avg_duration_ms)
            VALUES (:a, now(), CASE WHEN :ok THEN now() ELSE NULL END,
                    CASE WHEN :ok THEN 1 ELSE 0 END, CASE WHEN :ok THEN 0 ELSE 1 END,
                    :err, :dur)
            ON CONFLICT (adapter) DO UPDATE SET
              last_run_at = now(),
              last_success_at = CASE WHEN :ok THEN now() ELSE adapter_health.last_success_at END,
              success_count = adapter_health.success_count + CASE WHEN :ok THEN 1 ELSE 0 END,
              fail_count = adapter_health.fail_count + CASE WHEN :ok THEN 0 ELSE 1 END,
              last_error = :err,
              avg_duration_ms = COALESCE(
                  (adapter_health.avg_duration_ms * adapter_health.success_count + :dur)
                  / NULLIF(adapter_health.success_count + CASE WHEN :ok THEN 1 ELSE 0 END, 0),
                  :dur)
            """
        ),
        {"a": adapter, "ok": ok, "err": error, "dur": duration_ms},
    )


CAMPUS_TITLE_HINTS = ("校招", "校园", "应届", "應屆", "管培生", "培训生", "培訓生", "秋招", "春招", "2027届", "2027屆")


def _org_level(p: base.JobPosting) -> str:
    """總部/分支機構標記：raw deptype → tab 標籤 → 標題啟發式。"""
    raw = p.raw or {}
    dt = str(raw.get("deptype") or "").lower()
    if dt == "headquarter":
        return "headquarter"
    if dt == "branch":
        return "branch"
    tab = str(raw.get("tab") or "")
    if "分支" in tab or "branch" in tab.lower():
        return "branch"
    if "總部" in tab or "headquarter" in tab.lower():
        return "headquarter"
    title = p.title or ""
    if any(h in title for h in ("分公司", "营业部", "營業部", "支行")):
        return "branch"
    return "unknown"


def _is_intern_posting(p: base.JobPosting) -> bool:
    """實習判定：raw 標記 > 標題/標籤關鍵詞。"""
    if p.raw.get("is_intern"):
        return True
    title = (p.title or "").lower()
    tab = str(p.raw.get("tab") or "").lower()
    return any(h in title for h in ("實習", "实习", "intern")) or "實習" in tab or "实习" in tab


def _is_campus_posting(p: base.JobPosting) -> bool:
    if p.raw.get("is_campus"):
        return True
    title = (p.title or "").lower()
    return any(h.lower() in title for h in CAMPUS_TITLE_HINTS)


def store_postings(db: Session, postings: list[base.JobPosting]) -> dict:
    """按 (source, external_id) upsert；更新 last_seen_at/is_active。"""
    new = updated = 0
    seen: dict[tuple[str, str], str] = {}
    for p in postings:
        if not p.external_id or not p.title:
            continue
        seen[(p.source, p.company_name)] = seen.get((p.source, p.company_name), "")  # 佔位
        row = db.execute(
            text("SELECT id FROM job_postings WHERE source=:s AND external_id=:e"),
            {"s": p.source, "e": p.external_id},
        ).first()
        if row:
            db.execute(
                text(
                    """
                    UPDATE job_postings SET
                      title=:t, location=:loc, department=:dep,
                      description_text=COALESCE(:desc, description_text),
                      apply_url=COALESCE(:url, apply_url),
                      salary_range=COALESCE(CAST(:sal AS jsonb), salary_range),
                      posted_at=COALESCE(:posted, posted_at),
                      is_campus=:is_campus,
                      is_intern=:is_intern,
                      org_level=:org_level,
                      company_name=:cname,
                      last_seen_at=now(), is_active=true, raw=CAST(:raw AS jsonb)
                    WHERE id=:id
                    """
                ),
                {
                    "id": row[0], "t": p.title, "loc": p.location, "dep": p.department,
                    "desc": p.description_text, "url": p.apply_url,
                    "sal": json.dumps(p.salary_range, ensure_ascii=False) if p.salary_range else None,
                    "posted": p.posted_at, "cname": p.company_name,
                    "is_campus": _is_campus_posting(p),
                    "is_intern": _is_intern_posting(p),
                    "org_level": _org_level(p),
                    "raw": json.dumps(p.raw, ensure_ascii=False),
                },
            )
            updated += 1
        else:
            db.execute(
                text(
                    """
                    INSERT INTO job_postings
                      (source, external_id, company_name, title, location, department,
                       description_text, apply_url, salary_range, posted_at, is_campus,
                       is_intern, org_level, raw)
                    VALUES (:s, :e, :cname, :t, :loc, :dep, :desc, :url,
                            CAST(:sal AS jsonb), :posted, :is_campus, :is_intern, :org_level,
                            CAST(:raw AS jsonb))
                    """
                ),
                {
                    "s": p.source, "e": p.external_id, "cname": p.company_name,
                    "t": p.title, "loc": p.location, "dep": p.department,
                    "desc": p.description_text, "url": p.apply_url,
                    "sal": json.dumps(p.salary_range, ensure_ascii=False) if p.salary_range else None,
                    "posted": p.posted_at,
                    "is_campus": _is_campus_posting(p),
                    "is_intern": _is_intern_posting(p),
                    "org_level": _org_level(p),
                    "raw": json.dumps(p.raw, ensure_ascii=False),
                },
            )
            new += 1
    db.commit()
    _mark_stale(db, postings)
    return {"new": new, "updated": updated}


def _mark_stale(db: Session, postings: list[base.JobPosting]) -> None:
    """本次採集未出現、且超過 STALE_AFTER_DAYS 未見的崗位標記下架。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_AFTER_DAYS)
    for source in {p.source for p in postings}:
        for company in {p.company_name for p in postings if p.source == source}:
            db.execute(
                text(
                    """
                    UPDATE job_postings SET is_active=false
                    WHERE source=:s AND company_name=:c AND is_active=true
                      AND last_seen_at < :cutoff
                    """
                ),
                {"s": source, "c": company, "cutoff": cutoff},
            )
    db.commit()


def _user_targets(db: Session, user_id: str) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT company_name, aliases, careers_url, platform FROM watched_companies "
            "WHERE user_id=:uid AND is_active=true ORDER BY created_at"
        ),
        {"uid": user_id},
    ).mappings().all()
    targets = []
    for r in rows:
        url = r["careers_url"]
        platform = r["platform"]
        if platform in ("official", "other") and url:
            platform = detect_platform(url)
        targets.append(
            {
                "company_name": r["company_name"],
                "aliases": r["aliases"] or [],
                "careers_url": url,
                "platform": platform,
            }
        )
    return targets


def collect_for_user(db: Session, user_id: str, company_name: str | None = None,
                     skip_match: bool = False) -> dict:
    """對用戶的關注公司執行採集 + 匹配（可只採集指定公司）。返回報告。"""
    report = {"targets": [], "collected": 0, "new": 0, "updated": 0, "matched": 0, "errors": 0}
    from app.core.textutil import t2s as _t2s

    targets = _user_targets(db, user_id)
    if company_name:
        targets = [t for t in targets
                   if company_name.lower() in (t["company_name"] or "").lower()
                   or company_name.lower() in _t2s(t["company_name"] or "").lower()
                   or company_name.lower() in str(t.get("aliases") or "").lower()]
        if not targets:
            report["errors"] += 1
            report["targets"].append({"company": company_name, "platform": "-",
                                      "count": 0, "error": "未在關注公司中找到該公司"})
    for target in targets:
        platform = target["platform"]
        try:
            collector = base.get_collector(platform)
        except KeyError:
            report["errors"] += 1
            logger.warning("跳過不支持的平台 %s（%s）", platform, target["company_name"])
            continue
        started = datetime.now(timezone.utc)
        try:
            postings = collector.collect(target)
            stats = store_postings(db, postings)
            report["collected"] += len(postings)
            report["new"] += stats["new"]
            report["updated"] += stats["updated"]
            report["targets"].append(
                {"company": target["company_name"], "platform": platform,
                 "count": len(postings), **stats}
            )
            _health(db, platform, True, None,
                    int((datetime.now(timezone.utc) - started).total_seconds() * 1000))
        except Exception as exc:  # noqa: BLE001
            report["errors"] += 1
            report["targets"].append(
                {"company": target["company_name"], "platform": platform,
                 "count": 0, "error": str(exc)[:300]}
            )
            _health(db, platform, False, str(exc)[:1000],
                    int((datetime.now(timezone.utc) - started).total_seconds() * 1000))
            logger.exception("採集失敗 %s (%s)", target["company_name"], platform)
    db.commit()

    report["matched"] = 0 if skip_match else match_new_for_user(db, user_id)
    return report


def match_new_for_user(db: Session, user_id: str) -> int:
    """為用戶匹配「關注公司的新崗位」（尚無 match 記錄的），cap 控制成本。"""
    targets = _user_targets(db, user_id)
    if not targets:
        return 0
    company_matches = []
    params: dict = {"uid": user_id}
    for i, t in enumerate(targets):
        names = [t["company_name"], *(t["aliases"] or [])]
        company_matches.append(f"p.company_name = ANY(CAST(:names{i} AS text[]))")
        params[f"names{i}"] = names
    rows = db.execute(
        text(
            f"""
            SELECT p.id FROM job_postings p
            WHERE p.is_active = true AND ({" OR ".join(company_matches)})
              AND NOT EXISTS (SELECT 1 FROM job_matches m
                              WHERE m.user_id = :uid AND m.posting_id = p.id)
            ORDER BY p.first_seen_at DESC
            LIMIT :cap
            """
        ),
        {**params, "cap": MATCH_CAP_PER_USER},
    ).mappings().all()
    if not rows:
        return 0
    has_profile = db.execute(
        text("SELECT 1 FROM candidate_profiles WHERE user_id=:uid AND is_current=true LIMIT 1"),
        {"uid": user_id},
    ).first()
    if not has_profile:
        logger.info("用戶 %s 尚無畫像，跳過匹配", user_id)
        return 0
    matched = 0
    for r in rows:
        try:
            score_posting(db, user_id, str(r["id"]))
            matched += 1
        except Exception:  # noqa: BLE001
            logger.exception("匹配失敗 user=%s posting=%s", user_id, r["id"])
    return matched


def collect_all_users(db: Session) -> dict:
    """調度器入口：合併所有用戶的關注目標（天然按公司去重）執行採集。"""
    users = db.execute(
        text(
            "SELECT p.id FROM profiles p "
            "WHERE p.deleted_at IS NULL AND EXISTS "
            "  (SELECT 1 FROM watched_companies w WHERE w.user_id=p.id AND w.is_active=true)"
        )
    ).mappings().all()
    total = {"users": len(users), "collected": 0, "new": 0, "errors": 0, "matched": 0}
    for u in users:
        try:
            r = collect_for_user(db, str(u["id"]))
            total["collected"] += r["collected"]
            total["new"] += r["new"]
            total["errors"] += r["errors"]
            total["matched"] += r["matched"]
        except Exception:  # noqa: BLE001
            logger.exception("用戶採集失敗 user=%s", u["id"])
            total["errors"] += 1
    return total
