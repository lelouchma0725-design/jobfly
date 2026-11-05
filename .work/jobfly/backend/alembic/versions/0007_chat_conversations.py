"""0007: AI 對話歷史（問答記錄）

Revision ID: 0007
Revises: 0006
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_conversations (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id uuid NOT NULL REFERENCES profiles(id),
          title text NOT NULL DEFAULT '新對話',
          messages jsonb NOT NULL DEFAULT '[]'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        ALTER TABLE chat_conversations ENABLE ROW LEVEL SECURITY;
        CREATE POLICY chat_conv_own ON chat_conversations FOR ALL
          USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_conversations")
