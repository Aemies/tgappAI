"""provider credentials, portfolio, company profiles

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "provider_credentials",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("provider_code", sa.String(32), nullable=False),
        sa.Column("encrypted_secret", sa.Text, nullable=False),
        sa.Column("key_suffix", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="untested"),
        sa.Column("last_tested_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(255)),
        sa.Column("requests_today", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("owner_user_id", "provider_code"),
    )
    op.create_table(
        "portfolio_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("inn", sa.String(12), nullable=False),
        sa.Column("subject_type", sa.String(16), nullable=False),
        sa.Column("label", sa.String(255)),
        sa.Column("monitoring_enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("fetch_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("fetch_error", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("owner_user_id", "inn"),
    )
    op.create_table(
        "company_profiles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("portfolio_item_id", sa.Integer, sa.ForeignKey("portfolio_items.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("summary", sa.JSON, nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="checko"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("company_profiles")
    op.drop_table("portfolio_items")
    op.drop_table("provider_credentials")
