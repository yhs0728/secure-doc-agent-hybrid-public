"""Upload a bounded synthetic batch and measure real worker completion time.

Use an isolated validation workspace. Cleanup deletes only this run's documents.
"""

import argparse
import json
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def benchmark(base_url, env_file, count, paragraphs, timeout, report):
    cfg = dotenv_values(env_file)
    run = uuid4().hex[:12]
    created = []
    created_lock = threading.Lock()
    result = {
        "time": datetime.now(timezone.utc).isoformat(),
        "run_id": run,
        "documents": count,
        "paragraphs_per_document": paragraphs,
        "passed": False,
    }
    with httpx.Client(base_url=base_url, timeout=30) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={
                "email": cfg["BOOTSTRAP_ADMIN_EMAIL"],
                "password": cfg["BOOTSTRAP_ADMIN_PASSWORD"],
            },
        )
        login.raise_for_status()
        client.headers["Authorization"] = "Bearer " + login.json()["access_token"]

        def upload(n):
            name = f"worker-benchmark-{run}-{n}.txt"
            text = f"Benchmark run {run}.\n" + "\n".join(
                f"Policy section {n}-{i}: remote access requires approved devices and multifactor authentication."
                for i in range(paragraphs)
            )
            response = client.post(
                "/api/v1/documents/upload",
                files={"file": (name, text.encode(), "text/plain")},
            )
            response.raise_for_status()
            document_id = response.json()["document_id"]
            with created_lock:
                created.append(document_id)
            return document_id

        started = time.monotonic()
        try:
            with ThreadPoolExecutor(max_workers=min(count, 4)) as pool:
                list(pool.map(upload, range(count)))
            pending = set(created)
            finished = []
            deadline = started + timeout
            while pending and time.monotonic() < deadline:
                for did in list(pending):
                    response = client.get("/api/v1/documents/" + did)
                    response.raise_for_status()
                    state = response.json()["processing_status"]
                    if state == "FAILED":
                        raise RuntimeError("Benchmark indexing failed")
                    if state == "READY":
                        pending.remove(did)
                        finished.append(time.monotonic() - started)
                if pending:
                    time.sleep(0.25)
            if pending:
                raise RuntimeError("Benchmark timed out")
            elapsed = time.monotonic() - started
            result.update(
                {
                    "passed": True,
                    "elapsed_seconds": round(elapsed, 3),
                    "documents_per_second": round(count / elapsed, 4),
                    "median_ready_seconds": round(statistics.median(finished), 3),
                    "max_ready_seconds": round(max(finished), 3),
                }
            )
        except Exception as exc:
            result["failure_type"] = type(exc).__name__
            raise
        finally:
            cleanup_failures = 0
            for did in created:
                try:
                    if not client.delete("/api/v1/documents/" + did).is_success:
                        cleanup_failures += 1
                except httpx.HTTPError:
                    cleanup_failures += 1
            result["cleanup_request_failures"] = cleanup_failures
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18182")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.microservices")
    parser.add_argument("--count", type=int, choices=range(1, 17), default=6)
    parser.add_argument("--paragraphs", type=int, default=40)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument(
        "--report", type=Path, default=ROOT / ".microservice-tests/workers.json"
    )
    args = parser.parse_args()
    print(
        json.dumps(
            benchmark(
                args.base_url,
                args.env_file,
                args.count,
                args.paragraphs,
                args.timeout,
                args.report,
            ),
            indent=2,
        )
    )
