"""0009: 崗位方向逐方向貼合度分數

Revision ID: 0009
Revises: 0008
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE job_matches ADD COLUMN IF NOT EXISTS direction_scores jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE job_matches DROP COLUMN IF EXISTS direction_scores")
