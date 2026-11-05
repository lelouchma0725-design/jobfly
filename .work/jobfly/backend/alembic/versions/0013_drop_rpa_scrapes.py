"""0013: 下線 RPA 瀏覽器擴展，清理抓取快照表

精簡版移除 RPA 擴展與 /api/rpa 路由，站點簡歷回傳/校驗功能一併下線，
因此刪除 rpa_scrapes 表。敏感字段改為服務端字段級加密（仍用 sensitive_enc 列）。

Revision ID: 0013
Revises: 0012
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rpa_scrapes")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rpa_scrapes (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id uuid NOT NULL REFERENCES profiles(id),
          site text NOT NULL,
          page_type text NOT NULL,
          data jsonb NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS rpa_scrapes_user_site_idx "
        "ON rpa_scrapes (user_id, site, created_at DESC)"
    )
