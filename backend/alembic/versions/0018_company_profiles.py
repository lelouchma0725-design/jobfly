"""0018: company_profiles 公司信號緩存（行業/規模/地區），供香港崗位精細化評分

Revision ID: 0018
Revises: 0017
"""
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS company_profiles (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            company_name text NOT NULL UNIQUE,
            industry text,          -- tech / finance / insurance / other
            size_bucket text,       -- small(0-50) / medium(50-200) / large(200+) / unknown
            region text,            -- hk / cn / other
            extra jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS company_profiles")
