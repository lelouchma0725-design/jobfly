"""0019: rpa_detail_log 詳情採集診斷日誌（文本長度 + AI 抽取結果）

Revision ID: 0019
Revises: 0018
"""
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rpa_detail_log (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            site text NOT NULL,
            external_id text NOT NULL,
            text_len int,
            extracted jsonb,
            status text,          -- ok / empty_text / llm_fail / no_row
            error text,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rpa_detail_log")
