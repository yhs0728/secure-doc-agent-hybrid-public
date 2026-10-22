"""Add reliable outbox delivery metadata.

Revision ID: 0002_outbox_delivery
Revises: 0001_initial
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_outbox_delivery"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outbox_events",
        sa.Column("dedupe_key", sa.String(length=255), nullable=True),
        schema="ops",
    )
    op.add_column(
        "outbox_events",
        sa.Column("max_attempts", sa.Integer(), server_default="10", nullable=False),
        schema="ops",
    )
    op.add_column(
        "outbox_events",
        sa.Column("locked_by", sa.String(length=200), nullable=True),
        schema="ops",
    )
    op.add_column(
        "outbox_events",
        sa.Column("error_message", sa.Text(), nullable=True),
        schema="ops",
    )
    op.create_unique_constraint(
        "uq_outbox_events_workspace_event_dedupe",
        "outbox_events",
        ["workspace_id", "event_type", "dedupe_key"],
        schema="ops",
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_outbox_events_workspace_event_dedupe",
        "outbox_events",
        schema="ops",
        type_="unique",
    )
    op.drop_column("outbox_events", "error_message", schema="ops")
    op.drop_column("outbox_events", "locked_by", schema="ops")
    op.drop_column("outbox_events", "max_attempts", schema="ops")
    op.drop_column("outbox_events", "dedupe_key", schema="ops")
