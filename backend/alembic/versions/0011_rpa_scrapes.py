"""0011: RPA 簡歷抓取快照（回傳/校驗用）

Revision ID: 0011
Revises: 0010
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rpa_scrapes (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id uuid NOT NULL REFERENCES profiles(id),
          site text NOT NULL,
          page_type text NOT NULL,
          data jsonb NOT NULL DEFAULT '[]'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        ALTER TABLE rpa_scrapes ENABLE ROW LEVEL SECURITY;
        CREATE POLICY rpa_scrapes_own ON rpa_scrapes FOR ALL
          USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rpa_scrapes")
