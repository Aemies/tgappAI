"""monitoring: snapshots, events, runs

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("notifications_enabled", sa.Boolean, nullable=False, server_default=sa.true()))
    with op.batch_alter_table("portfolio_items") as b:
        b.add_column(sa.Column("last_checked_at", sa.DateTime(timezone=True)))
        b.add_column(sa.Column("last_check_error", sa.String(255)))
    op.create_table(
        "monitor_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("portfolio_item_id", sa.Integer, sa.ForeignKey("portfolio_items.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("provider", sa.String(32), nullable=False, server_default="checko"),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("normalized_payload", sa.JSON, nullable=False),
        sa.Column("timeline_last_date", sa.String(10)),
        sa.Column("is_baseline", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "registry_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("portfolio_item_id", sa.Integer, sa.ForeignKey("portfolio_items.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("event_key", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("details", sa.JSON, nullable=False),
        sa.Column("related_ogrn", sa.String(15)),
        sa.Column("effective_date", sa.String(10)),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("is_baseline", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("notified_at", sa.DateTime(timezone=True)),
        sa.Column("notify_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("portfolio_item_id", "event_key"),
    )
    op.create_table(
        "monitor_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("local_date", sa.String(10), nullable=False),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("checked", sa.Integer, nullable=False, server_default="0"),
        sa.Column("errors", sa.Integer, nullable=False, server_default="0"),
        sa.Column("skipped_quota", sa.Integer, nullable=False, server_default="0"),
        sa.Column("new_events", sa.Integer, nullable=False, server_default="0"),
        sa.Column("requests_used", sa.Integer, nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_table("monitor_runs")
    op.drop_table("registry_events")
    op.drop_table("monitor_snapshots")
    with op.batch_alter_table("portfolio_items") as b:
        b.drop_column("last_check_error")
        b.drop_column("last_checked_at")
    with op.batch_alter_table("users") as b:
        b.drop_column("notifications_enabled")
