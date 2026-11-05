"""0008: 採集進度狀態（供前台輪詢提示）

Revision ID: 0008
Revises: 0007
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS collect_state jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE user_settings DROP COLUMN IF EXISTS collect_state")
