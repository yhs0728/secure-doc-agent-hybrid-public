"""Durable, at-least-once jobs owned exclusively by the knowledge service."""

import argparse
import logging
import os
import threading
import time
from uuid import uuid4

from botocore.exceptions import ClientError

from . import storage
from .execution import process
from .platform import db, migrate

logger = logging.getLogger(__name__)
LEASE_SECONDS = 300
MAX_ATTEMPTS = 8


def claim():
    with db() as conn:
        return conn.execute(
            """UPDATE jobs SET status='RUNNING',attempts=attempts+1,
            lease_token=%s,started_at=now(),leased_until=now()+make_interval(secs=>%s)
            WHERE id=(SELECT id FROM jobs WHERE (status='PENDING' AND available_at<=now())
                OR (status='RUNNING' AND leased_until<now())
                ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *""",
            (uuid4(), LEASE_SECONDS),
        ).fetchone()


def heartbeat(job, stop):
    while not stop.wait(LEASE_SECONDS / 3):
        try:
            with db() as conn:
                conn.execute(
                    "UPDATE jobs SET leased_until=now()+make_interval(secs=>%s) WHERE id=%s AND lease_token=%s AND status='RUNNING'",
                    (LEASE_SECONDS, job["id"], job["lease_token"]),
                )
        except Exception:
            logger.exception("Job lease renewal failed job=%s", job["id"])


def fail(job, error=None):
    permanent_codes = {
        "CSV_FIELD_LIMIT_EXCEEDED",
        "INVALID_CSV",
        "EMPTY_DOCUMENT",
        "EXTRACTED_TEXT_LIMIT_EXCEEDED",
        "DOCUMENT_CHUNK_LIMIT_EXCEEDED",
        "DOCX_EXPANSION_LIMIT_EXCEEDED",
    }
    code = (
        str(error)
        if isinstance(error, ValueError) and str(error) in permanent_codes
        else "DOCUMENT_PROCESSING_FAILED"
    )
    with db(
        {
            "workspace_id": job["workspace_id"],
            "user_id": "00000000-0000-7000-8000-000000000001",
        }
    ) as conn:
        final = code != "DOCUMENT_PROCESSING_FAILED" or job["attempts"] >= MAX_ATTEMPTS
        owned = conn.execute(
            """UPDATE jobs SET status=%s,error_code=%s,leased_until=NULL,
            available_at=now()+make_interval(secs=>%s) WHERE id=%s AND lease_token=%s RETURNING id""",
            (
                "FAILED" if final else "PENDING",
                code,
                min(2 ** job["attempts"], 300),
                job["id"],
                job["lease_token"],
            ),
        ).fetchone()
        if owned:
            conn.execute(
                "UPDATE documents SET error_code=%s,state=CASE WHEN %s AND state<>'DELETING' THEN 'FAILED' ELSE state END,updated_at=now() WHERE id=%s AND state<>'DELETED'",
                (code, final, job["document_id"]),
            )


def run_once():
    job = claim()
    if not job:
        return False
    stop = threading.Event()
    thread = threading.Thread(target=heartbeat, args=(job, stop), daemon=True)
    thread.start()
    try:
        process(job)
    except Exception as exc:
        logger.exception("Job failed job=%s kind=%s", job["id"], job["kind"])
        fail(job, exc)
    finally:
        stop.set()
        thread.join(timeout=6)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    migrate()
    try:
        storage.object_store().head_bucket(Bucket=storage.bucket())
    except ClientError as error:
        # HeadBucket exposes generic HTTP failures rather than modeled NoSuchBucket.
        # Only a missing bucket justifies provisioning; 403/5xx/connectivity propagate.
        if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 404:
            raise
        storage.object_store().create_bucket(Bucket=storage.bucket())
    while True:
        processed = run_once()
        if args.once:
            break
        if not processed:
            time.sleep(2)


if __name__ == "__main__":
    main()
