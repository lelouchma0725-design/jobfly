"""0010: task_type 枚舉加 citics_manual

Revision ID: 0010
Revises: 0009
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE task_type ADD VALUE IF NOT EXISTS 'citics_manual'")


def downgrade() -> None:
    pass  # 枚舉值不回滾
