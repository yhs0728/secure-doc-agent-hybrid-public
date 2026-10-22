from __future__ import annotations

import argparse
import logging
import time

from app.runtime import update_persisted_index
from config.settings import get_settings
from services.outbox_service import run_outbox_batch
from services.postgres_ingestion_service import run_pending_ingestion_jobs

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="SecureDoc ingestion worker")
    parser.add_argument("--once", action="store_true", help="대기 작업을 한 번만 처리")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit은 1 이상이어야 합니다.")
    if args.poll_seconds <= 0:
        parser.error("--poll-seconds는 0보다 커야 합니다.")

    settings = get_settings()
    if not settings.database_enabled:
        raise SystemExit("DATABASE_ENABLED=true가 필요합니다.")

    while True:
        outbox_succeeded, outbox_failed = run_outbox_batch(settings)
        succeeded, failed = run_pending_ingestion_jobs(
            settings,
            update_persisted_index,
            limit=args.limit,
        )
        logger.info(
            "worker: outbox_succeeded=%s outbox_failed=%s "
            "ingestion_succeeded=%s ingestion_failed=%s",
            outbox_succeeded,
            outbox_failed,
            succeeded,
            failed,
        )
        if args.once:
            print(
                f"outbox_succeeded={outbox_succeeded} "
                f"outbox_failed={outbox_failed} "
                f"ingestion_succeeded={succeeded} ingestion_failed={failed}"
            )
            return
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
