from __future__ import annotations

import hashlib
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import text

from database.session import get_engine


def advisory_lock_key(workspace_id: UUID, resource: str) -> int:
    digest = hashlib.sha256(f"{workspace_id}:{resource}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


@contextmanager
def workspace_advisory_lock(workspace_id: UUID, resource: str):
    """Serialize a workspace resource across processes and hosts."""
    key = advisory_lock_key(workspace_id, resource)
    with get_engine().connect() as connection:
        connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": key})
        try:
            yield
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
