"""0005: 校招標記 + 校招/社招投遞偏好

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS is_campus boolean NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS campus_preference text NOT NULL DEFAULT 'both'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE user_settings DROP COLUMN IF EXISTS campus_preference")
    op.execute("ALTER TABLE job_postings DROP COLUMN IF EXISTS is_campus")
