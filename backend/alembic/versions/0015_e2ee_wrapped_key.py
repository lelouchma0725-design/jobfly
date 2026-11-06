"""0015: E2EE 密鑰恢復碼包裝密鑰

Revision ID: 0015
Revises: 0014
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS e2ee_wrapped_key text"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE user_settings DROP COLUMN IF EXISTS e2ee_wrapped_key")
