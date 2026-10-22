"""Create the initial multi-tenant SecureDoc schema.

Revision ID: 0001_initial
Revises: None
Create Date: 2026-10-07
"""

from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    schema_path = Path(__file__).resolve().parents[2] / "schema" / "0001_initial.sql"
    sql = schema_path.read_text(encoding="utf-8")
    for statement in sql.split(";"):
        normalized = statement.strip()
        if normalized:
            op.execute(sa.text(normalized))


def downgrade() -> None:
    # The schemas are owned by this application. CASCADE is intentionally
    # restricted to those five exact schema names.
    for schema in ("ops", "chat", "rag", "content", "identity"):
        op.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
