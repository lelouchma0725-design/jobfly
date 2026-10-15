"""集成測試：需要真實 Postgres（Supabase）與 KEK。

運行方式：
    RUN_INTEGRATION=1 DATABASE_URL=postgresql://... KEK_BASE64=... \
    pytest tests/test_integration.py -q
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason="集成測試需 RUN_INTEGRATION=1 與 DATABASE_URL/KEK_BASE64",
)


@pytest.fixture(scope="module")
def db():
    from app.db import SessionLocal

    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def uid(db):
    user_id = str(uuid.uuid4())
    db.execute(
        text("INSERT INTO profiles (id, email, role) VALUES (:id, :e, 'user')"),
        {"id": user_id, "e": f"it-{user_id[:8]}@test.local"},
    )
    db.commit()
    yield user_id
    # 按外鍵依賴順序清理
    for table in (
        "notifications", "manual_tasks", "application_attempts", "applications",
        "job_matches", "candidate_profiles", "resume_versions", "user_documents",
        "watched_companies", "platform_accounts", "user_settings",
    ):
        db.execute(text(f"DELETE FROM {table} WHERE user_id=:id"), {"id": user_id})
    db.execute(
        text("DELETE FROM key_wraps WHERE owner_type='user' AND owner_id=:id"),
        {"id": user_id},
    )
    db.execute(text("DELETE FROM profiles WHERE id=:id"), {"id": user_id})
    db.commit()


def test_schema_tables_exist(db):
    rows = db.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name IN "
            "('profiles','user_settings','platform_accounts','job_postings','job_matches',"
            "'applications','application_attempts','manual_tasks','notifications','key_wraps')"
        )
    ).scalars().all()
    assert len(rows) == 10


def test_user_settings_defaults(db, uid):
    db.execute(
        text("INSERT INTO user_settings (user_id) VALUES (:uid) ON CONFLICT DO NOTHING"),
        {"uid": uid},
    )
    db.commit()
    row = db.execute(
        text("SELECT match_threshold, auto_apply_mode, push_time_local FROM user_settings WHERE user_id=:uid"),
        {"uid": uid},
    ).mappings().one()
    assert row["match_threshold"] == 70
    assert row["auto_apply_mode"] == "threshold"
    assert str(row["push_time_local"]) == "08:00:00"


def test_envelope_encryption_roundtrip(db, uid):
    from app.core.security import decrypt_field, encrypt_field, get_dek_for_user

    dek = get_dek_for_user(db, uid)
    enc = encrypt_field(dek, "secret-密碼")
    assert "secret" not in enc
    assert decrypt_field(dek, enc) == "secret-密碼"
    # DEK 可重複取回
    assert get_dek_for_user(db, uid) == dek


def test_platform_account_encrypted_storage(db, uid):
    from app.core.security import encrypt_field, get_dek_for_user

    dek = get_dek_for_user(db, uid)
    db.execute(
        text(
            "INSERT INTO platform_accounts (user_id, platform, label, login_identifier_enc, password_enc) "
            "VALUES (:uid, 'greenhouse', '測試', :ident, :pwd)"
        ),
        {"uid": uid, "ident": encrypt_field(dek, "user@test.com"), "pwd": encrypt_field(dek, "p@ss")},
    )
    db.commit()
    row = db.execute(
        text("SELECT login_identifier_enc, password_enc FROM platform_accounts WHERE user_id=:uid"),
        {"uid": uid},
    ).mappings().one()
    # 數據庫中不可見明文
    assert "user@test.com" not in row["login_identifier_enc"]
    assert "p@ss" not in row["password_enc"]


def test_store_postings_upsert_dedupe(db):
    from app.collectors.base import JobPosting
    from app.collectors.pipeline import store_postings

    ext = f"it-{uuid.uuid4()}"
    p = JobPosting(source="lever", external_id=ext, company_name="測試公司", title="工程師")
    stats1 = store_postings(db, [p])
    assert stats1["new"] == 1
    stats2 = store_postings(db, [p])
    assert stats2["new"] == 0 and stats2["updated"] == 1  # 第二次為更新，不重複入庫
    db.execute(text("DELETE FROM job_postings WHERE source='lever' AND external_id=:e"), {"e": ext})
    db.commit()


def test_application_queue_and_unique(db, uid):
    from app.services.apply_engine import create_applications_from_matches

    ext = f"it-{uuid.uuid4()}"
    posting_id = db.execute(
        text(
            "INSERT INTO job_postings (source, external_id, company_name, title, apply_url, description_text) "
            "VALUES ('lever', :e, '測試公司', '工程師', 'https://example.com/apply', 'JD 內容') RETURNING id"
        ),
        {"e": ext},
    ).mappings().one()["id"]
    db.execute(
        text(
            "INSERT INTO job_matches (user_id, posting_id, match_score, status) "
            "VALUES (:uid, :pid, 88, 'new')"
        ),
        {"uid": uid, "pid": posting_id},
    )
    db.commit()
    r1 = create_applications_from_matches(db, uid)
    assert r1["mode"] == "threshold" and r1["created"] == 1
    # 冪等：再跑不重複建
    r2 = create_applications_from_matches(db, uid)
    assert r2["created"] == 0
    # 清理
    db.execute(text("DELETE FROM applications WHERE user_id=:uid"), {"uid": uid})
    db.execute(text("DELETE FROM job_matches WHERE user_id=:uid"), {"uid": uid})
    db.execute(text("DELETE FROM job_postings WHERE id=:pid"), {"pid": posting_id})
    db.commit()
