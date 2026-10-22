import json

from sqlalchemy import inspect, text

import database.models  # noqa: F401
from database.base import Base
from database.session import get_engine


def verify_database() -> dict[str, object]:
    engine = get_engine()
    expected_tables = set(Base.metadata.tables)

    with engine.connect() as connection:
        inspector = inspect(connection)
        actual_tables = {
            f"{schema}.{table}"
            for schema in ("identity", "content", "rag", "chat", "ops")
            for table in inspector.get_table_names(schema=schema)
        }
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        rls_policies = int(
            connection.scalar(
                text(
                    "SELECT count(*) FROM pg_policies "
                    "WHERE schemaname IN ('content', 'rag', 'chat')"
                )
            )
            or 0
        )

    missing = sorted(expected_tables - actual_tables)
    unexpected = sorted(actual_tables - expected_tables)
    return {
        "ok": not missing and revision == "0002_outbox_delivery" and rls_policies >= 6,
        "revision": revision,
        "expected_table_count": len(expected_tables),
        "actual_table_count": len(actual_tables),
        "missing_tables": missing,
        "unexpected_tables": unexpected,
        "rls_policy_count": rls_policies,
    }


if __name__ == "__main__":
    result = verify_database()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(1)
