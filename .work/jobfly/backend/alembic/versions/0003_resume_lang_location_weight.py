"""0003: 簡歷語言區分 + 期望地區權重

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE user_documents ADD COLUMN IF NOT EXISTS lang text NOT NULL DEFAULT 'zh'")
    op.execute("ALTER TABLE resume_versions ADD COLUMN IF NOT EXISTS lang text NOT NULL DEFAULT 'zh'")
    op.execute("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS preferred_locations jsonb")
    op.execute("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS location_weight int NOT NULL DEFAULT 10")


def downgrade() -> None:
    op.execute("ALTER TABLE user_settings DROP COLUMN IF EXISTS location_weight")
    op.execute("ALTER TABLE user_settings DROP COLUMN IF EXISTS preferred_locations")
    op.execute("ALTER TABLE resume_versions DROP COLUMN IF EXISTS lang")
    op.execute("ALTER TABLE user_documents DROP COLUMN IF EXISTS lang")
