"""finance reports, personal AI connections, AI usage log

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _ts(name, **kw):
    return sa.Column(name, sa.DateTime(timezone=True), **kw)


def upgrade():
    op.create_table(
        "finance_reports",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("portfolio_item_id", sa.Integer, sa.ForeignKey("portfolio_items.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("payload", sa.JSON, nullable=False),
        _ts("fetched_at", nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "ai_connections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("provider_code", sa.String(32), nullable=False),
        sa.Column("auth_type", sa.String(16), nullable=False, server_default="api_key"),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("model_id", sa.String(200)),
        sa.Column("encrypted_secret", sa.Text, nullable=False),
        sa.Column("key_suffix", sa.String(8), nullable=False),
        sa.Column("settings", sa.JSON, nullable=False),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("data_level", sa.Integer, nullable=False, server_default="1"),
        sa.Column("monthly_request_limit", sa.Integer, nullable=False, server_default="100"),
        sa.Column("max_tokens", sa.Integer, nullable=False, server_default="1500"),
        sa.Column("status", sa.String(16), nullable=False, server_default="untested"),
        sa.Column("last_error", sa.String(255)),
        _ts("last_tested_at"),
        _ts("created_at", nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "ai_usage_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("connection_id", sa.Integer, sa.ForeignKey("ai_connections.id", ondelete="SET NULL"), index=True),
        sa.Column("provider_code", sa.String(32), nullable=False),
        sa.Column("model_id", sa.String(200)),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("input_tokens", sa.Integer),
        sa.Column("output_tokens", sa.Integer),
        _ts("created_at", nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("ai_usage_events")
    op.drop_table("ai_connections")
    op.drop_table("finance_reports")
