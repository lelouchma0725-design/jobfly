"""0004: 個人信息元信息表（投遞表單字段互補機制）

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_info_fields (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id uuid NOT NULL REFERENCES profiles(id),
          key text NOT NULL,
          value text NOT NULL,
          source text NOT NULL DEFAULT 'user',
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (user_id, key)
        );
        ALTER TABLE user_info_fields ENABLE ROW LEVEL SECURITY;
        CREATE POLICY user_info_fields_own ON user_info_fields FOR ALL
          USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_info_fields")
