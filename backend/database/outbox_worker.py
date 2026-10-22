from __future__ import annotations

import argparse
import time

from config.settings import get_settings
from services.outbox_service import run_outbox_batch


def main() -> None:
    parser = argparse.ArgumentParser(description="SecureDoc outbox publisher")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    settings = get_settings()
    if not settings.database_enabled:
        raise SystemExit("DATABASE_ENABLED=true가 필요합니다.")

    while True:
        succeeded, failed = run_outbox_batch(settings, limit=args.limit)
        print(f"outbox_succeeded={succeeded} outbox_failed={failed}")
        if args.once:
            return
        time.sleep(settings.outbox_poll_seconds)


if __name__ == "__main__":
    main()
