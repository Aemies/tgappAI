"""users

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("telegram_id", sa.BigInteger, nullable=False),
        sa.Column("first_name", sa.String(255)),
        sa.Column("username", sa.String(255)),
        sa.Column("language_code", sa.String(16)),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Europe/Moscow"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("accepted_terms_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)


def downgrade():
    op.drop_index("ix_users_telegram_id", "users")
    op.drop_table("users")
