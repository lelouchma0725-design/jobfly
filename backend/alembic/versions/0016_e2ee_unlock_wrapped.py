"""0016: 兩層密鑰 - 安全密鑰包裝的 E2EE 密鑰

Revision ID: 0016
Revises: 0015
"""
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS e2ee_unlock_wrapped text"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE user_settings DROP COLUMN IF EXISTS e2ee_unlock_wrapped")
