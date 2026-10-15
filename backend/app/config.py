"""應用配置：全部來自環境變量，缺失關鍵項時啟動即報錯（fail fast）。"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Supabase
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    database_url: str = ""

    # 信封加密 KEK
    kek_base64: str = ""

    # R2 對象存儲
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = "jobfly-documents"
    r2_public_base_url: str = ""

    # LLM
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_structured_model: str = "deepseek-chat"

    # 推送渠道
    wecom_webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    # 運行
    app_env: str = "dev"
    frontend_url: str = "http://localhost:5173"
    public_base_url: str = "http://localhost:8000"

    # 瀏覽器自動化
    playwright_browsers_path: str = ""

    # 管理員郵箱（逗號分隔；登錄時自動提升為 admin）
    admin_emails: str = ""

    @property
    def admin_email_list(self) -> list[str]:
        return [e.strip().lower() for e in self.admin_emails.split(",") if e.strip()]

    def missing_critical(self) -> list[str]:
        """列出缺失的關鍵配置（啟動時告警；首次使用時由各服務報錯）。"""
        missing: list[str] = []
        for name in ("supabase_url", "supabase_service_role_key", "database_url", "kek_base64"):
            if not getattr(self, name):
                missing.append(name.upper())
        return missing


settings = Settings()

# Playwright 在導入時讀取環境變量，這裡提前注入
import os

if settings.playwright_browsers_path:
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", settings.playwright_browsers_path)
