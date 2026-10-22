"""Real HTTP acceptance test; no adapters are replaced.

Credentials come from the ignored env file. Only documents created by this run are
deleted. Run against an isolated validation stack, not a production workspace.
"""

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def wait_ready(client, document_id, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = client.get("/api/v1/documents/" + document_id, timeout=5)
        except httpx.TransportError:
            time.sleep(2)
            continue
        if response.status_code in (502, 503, 504):
            time.sleep(2)
            continue
        response.raise_for_status()
        state = response.json().get("processing_status")
        if state == "READY":
            return
        if state == "FAILED":
            raise RuntimeError("Document worker exhausted retries")
        time.sleep(2)
    raise RuntimeError("Document did not become READY before the deadline")


def wait_rebuild(client, job_id, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get("/api/v1/index/jobs/" + job_id)
        response.raise_for_status()
        job = response.json()
        if job["status"] == "FAILED":
            raise RuntimeError("Atomic rebuild exhausted retries")
        if job["status"] == "DONE":
            generation = job.get("generation_after")
            if (
                not generation
                or generation == job.get("generation_before")
                or generation != job.get("active_generation")
            ):
                raise RuntimeError("Atomic rebuild did not publish a new generation")
            return job
        time.sleep(2)
    raise RuntimeError("Atomic rebuild did not finish")


def verify(base_url, env_file, timeout=600, report=None):
    config = dotenv_values(env_file)
    run = uuid4().hex[:12]
    name = "acceptance-" + run + ".txt"
    document_id = None
    result = {
        "time": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "run_id": run,
        "checks": {},
        "latencies_seconds": {},
    }
    with httpx.Client(
        base_url=base_url, timeout=httpx.Timeout(timeout, connect=5)
    ) as client:
        try:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    if client.get("/api/v1/ready", timeout=5).is_success:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("Knowledge API did not become ready")
            client.get("/api/v1/health").raise_for_status()
            result["checks"]["gateway"] = True
            response = client.post(
                "/api/v1/auth/login",
                json={
                    "email": config["BOOTSTRAP_ADMIN_EMAIL"],
                    "password": config["BOOTSTRAP_ADMIN_PASSWORD"],
                },
            )
            response.raise_for_status()
            client.headers["Authorization"] = (
                "Bearer " + response.json()["access_token"]
            )
            result["checks"]["login"] = True
            text = f"Acceptance run {run}. Security policy: all employee passwords must be changed every 90 days. This rule applies to all employees."
            start = time.monotonic()
            response = client.post(
                "/api/v1/documents/upload",
                files={"file": (name, text.encode(), "text/plain")},
            )
            response.raise_for_status()
            document_id = response.json()["document_id"]
            wait_ready(client, document_id, timeout)
            result["latencies_seconds"]["upload_to_ready"] = round(
                time.monotonic() - start, 3
            )
            result["checks"]["real_storage_embedding_index"] = True
            start = time.monotonic()
            response = client.post(
                "/api/v1/questions",
                json={"question": "직원의 비밀번호는 며칠마다 변경해야 하나요?"},
            )
            response.raise_for_status()
            answer = response.json()
            if (
                "90" not in answer["answer"]
                or name not in answer["citations"]
                or answer["requires_human_review"]
            ):
                raise RuntimeError(
                    "Real RAG did not produce the expected grounded answer"
                )
            result["latencies_seconds"]["rag"] = round(time.monotonic() - start, 3)
            result["checks"]["real_llm_grounded_answer"] = True
            cid = answer["conversation_id"]
            detail = client.get("/api/v1/conversations/" + cid)
            detail.raise_for_status()
            assert len(detail.json()["messages"]) >= 2
            result["checks"]["persistent_history"] = True
            rebuild = client.post("/api/v1/index/update")
            rebuild.raise_for_status()
            job = wait_rebuild(client, rebuild.json()["job_id"], timeout)
            result["rebuild"] = {
                key: job[key]
                for key in ("id", "status", "generation_before", "generation_after")
            }
            result["checks"]["rebuild_job_done_new_generation"] = True
            response = client.post(
                "/api/v1/questions",
                json={"question": "직원의 비밀번호 변경 주기는 며칠인가요?"},
            )
            response.raise_for_status()
            assert (
                name in response.json()["citations"]
                and "90" in response.json()["answer"]
            )
            result["checks"]["atomic_rebuild_search"] = True
            client.delete("/api/v1/documents/" + document_id).raise_for_status()
            remaining = client.get("/api/v1/documents")
            remaining.raise_for_status()
            has_other_ready = any(
                row.get("processing_status") == "READY" for row in remaining.json()
            )
            response = client.post(
                "/api/v1/questions",
                json={"question": "직원의 비밀번호 변경 주기는 며칠인가요?"},
            )
            response.raise_for_status()
            answer = response.json()
            assert name not in answer["citations"]
            # Other existing documents may independently support the same answer.
            # Require abstention only when this workspace has no READY sources.
            if not has_other_ready:
                assert answer["requires_human_review"]
                result["checks"]["empty_knowledge_requires_human_review"] = True
            result["checks"]["delete_excluded_from_new_answers"] = True
            result["passed"] = True
        except Exception as exc:
            # No tokens, passwords or document bodies in the report.
            result["passed"] = False
            result["failure_type"] = type(exc).__name__
            if isinstance(exc, httpx.HTTPStatusError):
                result["http_status"] = exc.response.status_code
                try:
                    code = exc.response.json().get("error", {}).get("code")
                    if isinstance(code, str) and re.fullmatch(
                        r"[A-Z][A-Z0-9_]{0,79}", code
                    ):
                        result["error_code"] = code
                except (ValueError, AttributeError):
                    pass
            raise
        finally:
            if document_id:
                try:
                    client.delete("/api/v1/documents/" + document_id)
                except httpx.HTTPError:
                    pass
            if report:
                report.parent.mkdir(parents=True, exist_ok=True)
                report.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18182")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.microservices")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument(
        "--report", type=Path, default=ROOT / ".microservice-tests/full-stack.json"
    )
    args = parser.parse_args()
    print(
        json.dumps(
            verify(args.base_url, args.env_file, args.timeout, args.report),
            ensure_ascii=False,
            indent=2,
        )
    )
