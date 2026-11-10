"""0017: user_settings 加 accept_contract_hk（是否接受香港地區 Contract 合同工）

Revision ID: 0017
Revises: 0016
"""
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS accept_contract_hk boolean NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE user_settings DROP COLUMN IF EXISTS accept_contract_hk")
