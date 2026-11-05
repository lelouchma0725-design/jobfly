"""0012: 元信息敏感字段端到端加密列（隱私方案第二層）

Revision ID: 0012
Revises: 0011
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE user_info_fields ADD COLUMN IF NOT EXISTS sensitive_enc text"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE user_info_fields DROP COLUMN IF EXISTS sensitive_enc")
