"""0013: 實習崗位標記

Revision ID: 0013
Revises: 0012
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS is_intern boolean NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE job_postings DROP COLUMN IF EXISTS is_intern")
