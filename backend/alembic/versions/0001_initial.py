"""initial schema: 全部業務表 + RLS 多租戶隔離

Revision ID: 0001
Revises:
Create Date: 2025-01-01

對應 docs/02-數據模型.md。多租戶隔離策略：
- 用戶數據表：RLS `auth.uid() = user_id`，後端（postgres/service_role）繞過 RLS，
  但代碼層仍強制 user_id 過濾（雙重保證）。
- 全局表（job_postings/companies_catalog）：登錄用戶可讀，寫入僅服務端。
- 管理表（key_wraps/audit_logs/collect_jobs/ai_jobs/adapter_health）：RLS 開啟但無策略，
  僅 postgres/service_role 可訪問。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

uuid = postgresql.UUID(as_uuid=True)
jsonb = postgresql.JSONB

ENUMS: dict[str, tuple[str, ...]] = {
    "user_role": ("user", "admin"),
    "auto_apply_mode": ("off", "threshold", "all"),
    "platform_name": (
        "workday", "greenhouse", "lever", "successfactors", "icims", "official",
        "liepin", "boss", "lagou", "zhilian", "job51", "linkedin", "indeed", "other",
    ),
    "account_status": ("pending_verify", "active", "expired", "locked", "error"),
    "owner_type": ("user", "system"),
    "doc_type": ("resume", "cover_letter", "transcript", "visa", "certificate", "portfolio", "other"),
    "parse_status": ("pending", "parsing", "parsed", "failed", "ocr"),
    "created_by": ("user", "ai"),
    "ats_type": ("workday", "greenhouse", "lever", "successfactors", "icims", "other"),
    "match_status": (
        "new", "pushed", "applying", "applied",
        "skipped_below_threshold", "hard_failed", "expired", "ignored",
    ),
    "application_status": (
        "queued", "in_progress", "submitted", "failed_retryable",
        "needs_input", "aborted", "duplicate_skip", "not_supported",
    ),
    "attempt_result": ("success", "failed", "manual_input_needed", "aborted"),
    "task_type": ("captcha", "login_required", "missing_field", "missing_file", "confirm_content", "other"),
    "task_status": ("open", "answered", "cancelled", "expired"),
    "notify_channel": ("pushplus", "wecom", "email", "in_app"),
    "notify_kind": ("daily_digest", "apply_result", "manual_task", "login_expired", "system"),
    "notify_status": ("queued", "sent", "failed"),
    "collect_kind": ("collect", "push", "retry", "cleanup", "heartbeat"),
    "collect_status": ("pending", "running", "done", "failed"),
    "ai_kind": ("parse_document", "build_profile", "score_match", "optimize_resume", "cover_letter"),
}


def _enum(name: str) -> sa.Enum:
    return sa.Enum(*ENUMS[name], name=name, create_type=False)


def _pk(col: str = "id") -> sa.Column:
    return sa.Column(col, uuid, primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _fk(col: str, target: str, nullable: bool = False) -> sa.Column:
    return sa.Column(col, uuid, sa.ForeignKey(target), nullable=nullable)


def _ts(name: str = "created_at", server_default: bool = True) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.func.now() if server_default else None,
    )


def _updateable_table() -> list[sa.Column]:
    return [_ts("created_at"), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now())]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    for name, values in ENUMS.items():
        op.execute(f"CREATE TYPE {name} AS ENUM ({', '.join(repr(v) for v in values)})")

    # ── 1. profiles（擴展 auth.users）────────────────────────────────
    op.create_table(
        "profiles",
        _pk(),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("full_name", sa.Text(), nullable=True),
        sa.Column("role", _enum("user_role"), server_default="user", nullable=False),
        sa.Column("locale", sa.Text(), server_default="zh-CN", nullable=False),
        sa.Column("tos_accepted_at", sa.DateTime(timezone=True), nullable=True),
        *_updateable_table(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── 2. user_settings ──────────────────────────────────────────────
    op.create_table(
        "user_settings",
        _fk("user_id", "profiles.id"),
        sa.Column("ai_optimize_resume", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("ai_optimize_cover_letter", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("match_threshold", sa.Integer(), server_default="70", nullable=False),
        sa.Column("auto_apply_mode", _enum("auto_apply_mode"), server_default="threshold", nullable=False),
        sa.Column("apply_rate_limit_min", sa.Integer(), server_default="5", nullable=False),
        sa.Column("push_channels", jsonb, nullable=True),
        sa.Column("push_time_local", sa.Time(), server_default="08:00", nullable=False),
        sa.Column("timezone", sa.Text(), server_default="Asia/Shanghai", nullable=False),
        sa.Column("daily_digest_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("login_expiry_notify", sa.Boolean(), server_default="true", nullable=False),
        *_updateable_table(),
        sa.PrimaryKeyConstraint("user_id"),
    )

    # ── 3. platform_accounts（加密存儲）──────────────────────────────
    op.create_table(
        "platform_accounts",
        _pk(),
        _fk("user_id", "profiles.id"),
        sa.Column("platform", _enum("platform_name"), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("login_identifier_enc", sa.Text(), nullable=False),
        sa.Column("password_enc", sa.Text(), nullable=False),
        sa.Column("cookie_state_enc", sa.Text(), nullable=True),
        sa.Column("meta_enc", sa.Text(), nullable=True),
        sa.Column("status", _enum("account_status"), server_default="pending_verify", nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        *_updateable_table(),
    )

    # ── 4. key_wraps（信封加密，管理表）──────────────────────────────
    op.create_table(
        "key_wraps",
        _pk(),
        sa.Column("owner_type", _enum("owner_type"), nullable=False),
        sa.Column("owner_id", uuid, nullable=False),
        sa.Column("wrapped_dek", sa.Text(), nullable=False),
        sa.Column("kek_version", sa.Integer(), server_default="1", nullable=False),
        _ts("created_at"),
        sa.UniqueConstraint("owner_type", "owner_id"),
    )

    # ── 5. user_documents ─────────────────────────────────────────────
    op.create_table(
        "user_documents",
        _pk(),
        _fk("user_id", "profiles.id"),
        sa.Column("doc_type", _enum("doc_type"), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("mime", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("parsed_text", sa.Text(), nullable=True),
        sa.Column("structured_json", jsonb, nullable=True),
        sa.Column("parse_status", _enum("parse_status"), server_default="pending", nullable=False),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        *_updateable_table(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── 6. resume_versions（AI 微調審計）─────────────────────────────
    op.create_table(
        "resume_versions",
        _pk(),
        _fk("user_id", "profiles.id"),
        _fk("source_document_id", "user_documents.id", nullable=True),
        _fk("base_version_id", "resume_versions.id", nullable=True),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=True),
        sa.Column("cover_letter_md", sa.Text(), nullable=True),
        sa.Column("created_by", _enum("created_by"), nullable=False),
        sa.Column("optimization_prompt", sa.Text(), nullable=True),
        sa.Column("optimization_context", jsonb, nullable=True),
        sa.Column("diff_summary", sa.Text(), nullable=True),
        _ts("created_at"),
        sa.UniqueConstraint("user_id", "version_no"),
    )

    # ── 7. candidate_profiles（AI 畫像，多版本）──────────────────────
    op.create_table(
        "candidate_profiles",
        _pk(),
        _fk("user_id", "profiles.id"),
        _fk("based_on_resume_version_id", "resume_versions.id", nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("skills", jsonb, nullable=True),
        sa.Column("experiences", jsonb, nullable=True),
        sa.Column("education", jsonb, nullable=True),
        sa.Column("hard_facts", jsonb, nullable=True),
        sa.Column("suggested_roles", jsonb, nullable=True),
        sa.Column("model_used", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default="false", nullable=False),
    )

    # ── 8. watched_companies / companies_catalog ─────────────────────
    op.create_table(
        "watched_companies",
        _pk(),
        _fk("user_id", "profiles.id"),
        sa.Column("company_name", sa.Text(), nullable=False),
        sa.Column("aliases", jsonb, nullable=True),
        sa.Column("careers_url", sa.Text(), nullable=True),
        sa.Column("platform", _enum("platform_name"), server_default="official", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        *_updateable_table(),
    )
    op.create_table(
        "companies_catalog",
        _pk(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("aliases", jsonb, nullable=True),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column("careers_url_template", sa.Text(), nullable=True),
        sa.Column("ats_type", _enum("ats_type"), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        _ts("created_at"),
        sa.UniqueConstraint("name"),
    )

    # ── 9. job_postings（全局崗位池）─────────────────────────────────
    op.create_table(
        "job_postings",
        _pk(),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("company_name", sa.Text(), nullable=False),
        _fk("catalog_company_id", "companies_catalog.id", nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("department", sa.Text(), nullable=True),
        sa.Column("description_text", sa.Text(), nullable=True),
        sa.Column("apply_url", sa.Text(), nullable=True),
        sa.Column("salary_range", jsonb, nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("raw", jsonb, nullable=True),
        _ts("created_at"),
        sa.UniqueConstraint("source", "external_id"),
    )

    # ── 10. job_matches ───────────────────────────────────────────────
    op.create_table(
        "job_matches",
        _pk(),
        _fk("user_id", "profiles.id"),
        _fk("posting_id", "job_postings.id"),
        _fk("profile_version_id", "candidate_profiles.id", nullable=True),
        sa.Column("match_score", sa.Integer(), nullable=True),
        sa.Column("hard_failures", jsonb, nullable=True),
        sa.Column("score_breakdown", jsonb, nullable=True),
        sa.Column("reasons", jsonb, nullable=True),
        sa.Column("status", _enum("match_status"), server_default="new", nullable=False),
        *_updateable_table(),
        sa.UniqueConstraint("user_id", "posting_id"),
    )

    # ── 11. applications（投遞狀態機）────────────────────────────────
    op.create_table(
        "applications",
        _pk(),
        _fk("user_id", "profiles.id"),
        _fk("posting_id", "job_postings.id"),
        _fk("match_id", "job_matches.id", nullable=True),
        _fk("resume_version_id", "resume_versions.id", nullable=True),
        _fk("cover_letter_version_id", "resume_versions.id", nullable=True),
        sa.Column("status", _enum("application_status"), server_default="queued", nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("current_step", sa.Text(), nullable=True),
        sa.Column("external_ref", sa.Text(), nullable=True),
        sa.Column("attempts_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        *_updateable_table(),
        sa.UniqueConstraint("user_id", "posting_id"),
    )

    # ── 12. application_attempts ──────────────────────────────────────
    op.create_table(
        "application_attempts",
        _pk(),
        _fk("user_id", "profiles.id"),
        _fk("application_id", "applications.id"),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", _enum("attempt_result"), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_detail", jsonb, nullable=True),
        sa.Column("screenshots", jsonb, nullable=True),
        sa.Column("trace", sa.Text(), nullable=True),
    )

    # ── 13. manual_tasks（人工接管）──────────────────────────────────
    op.create_table(
        "manual_tasks",
        _pk(),
        _fk("user_id", "profiles.id"),
        _fk("application_id", "applications.id"),
        sa.Column("task_type", _enum("task_type"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("options", jsonb, nullable=True),
        sa.Column("screenshot_path", sa.Text(), nullable=True),
        sa.Column("answer", jsonb, nullable=True),
        sa.Column("status", _enum("task_status"), server_default="open", nullable=False),
        sa.Column("notify_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _ts("created_at"),
    )

    # ── 14. notifications ─────────────────────────────────────────────
    op.create_table(
        "notifications",
        _pk(),
        _fk("user_id", "profiles.id"),
        sa.Column("channel", _enum("notify_channel"), nullable=False),
        sa.Column("kind", _enum("notify_kind"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("meta", jsonb, nullable=True),
        sa.Column("status", _enum("notify_status"), server_default="queued", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        _ts("created_at"),
    )

    # ── 15. 系統表 ────────────────────────────────────────────────────
    op.create_table(
        "collect_jobs",
        _pk(),
        sa.Column("kind", _enum("collect_kind"), nullable=False),
        sa.Column("payload", jsonb, nullable=True),
        sa.Column("status", _enum("collect_status"), server_default="pending", nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("lock_key", sa.Text(), nullable=True),
        _ts("created_at"),
    )
    op.create_table(
        "ai_jobs",
        _pk(),
        _fk("user_id", "profiles.id", nullable=True),
        sa.Column("kind", _enum("ai_kind"), nullable=False),
        sa.Column("input_ref", jsonb, nullable=True),
        sa.Column("output_ref", jsonb, nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("status", _enum("collect_status"), server_default="pending", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        _ts("created_at"),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "adapter_health",
        _pk(),
        sa.Column("adapter", sa.Text(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("success_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fail_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("avg_duration_ms", sa.Integer(), nullable=True),
        _ts("created_at"),
        sa.UniqueConstraint("adapter"),
    )
    op.create_table(
        "audit_logs",
        _pk(),
        _fk("actor_user_id", "profiles.id", nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity", sa.Text(), nullable=True),
        sa.Column("entity_id", sa.Text(), nullable=True),
        sa.Column("meta", jsonb, nullable=True),
        sa.Column("ip", sa.Text(), nullable=True),
        _ts("created_at"),
    )

    # ── 索引 ──────────────────────────────────────────────────────────
    op.create_index("ix_postings_active_seen", "job_postings", ["is_active", "first_seen_at"])
    op.create_index("ix_postings_catalog", "job_postings", ["catalog_company_id"])
    op.create_index("ix_matches_user_status_score", "job_matches", ["user_id", "status", "match_score"])
    op.create_index("ix_apps_status_retry", "applications", ["status", "next_retry_at"])
    op.create_index("ix_tasks_status_expiry", "manual_tasks", ["status", "expires_at"])
    op.create_index("ix_notifications_status", "notifications", ["status", "created_at"])
    op.create_index("ix_accounts_user", "platform_accounts", ["user_id"])
    op.create_index("ix_documents_user", "user_documents", ["user_id", "doc_type"])
    op.create_index("ix_collect_pending", "collect_jobs", ["status", "scheduled_at"])
    op.create_index("ix_audit_created", "audit_logs", ["created_at"])

    # ── updated_at 自動維護觸發器 ─────────────────────────────────────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
        BEGIN NEW.updated_at = now(); RETURN NEW; END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in (
        "profiles", "user_settings", "platform_accounts", "user_documents",
        "watched_companies", "job_matches", "applications",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_updated
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            """
        )

    # ── RLS 多租戶隔離 ───────────────────────────────────────────────
    user_scoped = [
        "user_settings", "platform_accounts", "user_documents", "resume_versions",
        "candidate_profiles", "watched_companies", "job_matches", "applications",
        "application_attempts", "manual_tasks", "notifications",
    ]
    for table in user_scoped:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_own ON {table} FOR ALL "
            f"USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id)"
        )
    op.execute("ALTER TABLE profiles ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY profiles_own ON profiles FOR ALL "
        "USING (auth.uid() = id) WITH CHECK (auth.uid() = id)"
    )
    # 全局可讀表
    for table in ("job_postings", "companies_catalog"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_read ON {table} FOR SELECT TO authenticated USING (true)"
        )
    # 管理表：RLS 開啟但無策略 → 僅 postgres/service_role 可訪問
    for table in ("key_wraps", "collect_jobs", "ai_jobs", "adapter_health", "audit_logs"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    # ── 授權（後端使用 service_role/postgres；為前端直讀兜底）─────────
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO authenticated;"
    )
    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO authenticated;"
    )


def downgrade() -> None:
    tables = [
        "audit_logs", "adapter_health", "ai_jobs", "collect_jobs", "notifications",
        "manual_tasks", "application_attempts", "applications", "job_matches",
        "job_postings", "companies_catalog", "watched_companies", "candidate_profiles",
        "resume_versions", "user_documents", "key_wraps", "platform_accounts",
        "user_settings", "profiles",
    ]
    for table in tables:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at() CASCADE")
    for name in ENUMS:
        op.execute(f"DROP TYPE IF EXISTS {name}")
