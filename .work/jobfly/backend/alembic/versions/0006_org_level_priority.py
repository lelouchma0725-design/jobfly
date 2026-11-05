"""0006: 總部/分支機構標記 + 投遞優先級分 + 組織偏好

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS org_level text NOT NULL DEFAULT 'unknown'"
    )
    op.execute(
        "ALTER TABLE job_matches ADD COLUMN IF NOT EXISTS priority_score integer"
    )
    op.execute(
        "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS org_preference text NOT NULL DEFAULT 'both'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE user_settings DROP COLUMN IF EXISTS org_preference")
    op.execute("ALTER TABLE job_matches DROP COLUMN IF EXISTS priority_score")
    op.execute("ALTER TABLE job_postings DROP COLUMN IF EXISTS org_level")
