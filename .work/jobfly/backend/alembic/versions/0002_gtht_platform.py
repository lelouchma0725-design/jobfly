"""gtht: 新增國泰海通證券招聘平台

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid
            WHERE t.typname = 'platform_name' AND e.enumlabel = 'gtht'
          ) THEN
            ALTER TYPE platform_name ADD VALUE 'gtht';
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Postgres 不支持從枚舉中刪除值；此遷移無需回滾
    pass
