from __future__ import annotations

import json
import multiprocessing
import time
from dataclasses import asdict, dataclass
from queue import Empty

from config.settings import get_settings
from database.locks import workspace_advisory_lock
from database.verify import verify_database


@dataclass(frozen=True)
class LockWindow:
    worker: str
    entered_at: float
    exited_at: float


def _lock_worker(worker: str, start_event, results, hold_seconds: float) -> None:
    settings = get_settings()
    start_event.wait(timeout=10)
    with workspace_advisory_lock(
        settings.default_workspace_id,
        "operations-verification",
    ):
        entered_at = time.monotonic()
        time.sleep(hold_seconds)
        exited_at = time.monotonic()
    results.put(LockWindow(worker, entered_at, exited_at))


def verify_process_lock(hold_seconds: float = 0.5) -> dict[str, object]:
    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_lock_worker,
            args=(f"worker-{number}", start_event, results, hold_seconds),
        )
        for number in (1, 2)
    ]
    for process in processes:
        process.start()
    start_event.set()
    for process in processes:
        process.join(timeout=15)

    if any(process.is_alive() for process in processes):
        for process in processes:
            process.terminate()
        raise RuntimeError("Advisory-lock verification timed out.")
    if any(process.exitcode != 0 for process in processes):
        raise RuntimeError(
            f"Advisory-lock worker failed: {[process.exitcode for process in processes]}"
        )

    windows: list[LockWindow] = []
    try:
        for _ in processes:
            windows.append(results.get(timeout=2))
    except Empty as error:
        raise RuntimeError("Advisory-lock worker did not report a result.") from error
    windows.sort(key=lambda item: item.entered_at)
    serialized = [asdict(window) for window in windows]
    return {
        "ok": windows[1].entered_at >= windows[0].exited_at,
        "windows": serialized,
    }


def verify_operations() -> dict[str, object]:
    database = verify_database()
    process_lock = verify_process_lock() if database["ok"] else {"ok": False}
    return {
        "ok": bool(database["ok"] and process_lock["ok"]),
        "database": database,
        "multi_process_lock": process_lock,
    }


if __name__ == "__main__":
    verification = verify_operations()
    print(json.dumps(verification, ensure_ascii=False, indent=2))
    if not verification["ok"]:
        raise SystemExit(1)
