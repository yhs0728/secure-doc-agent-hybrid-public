"""Regression coverage for false-positive rebuild acceptance results."""

import importlib.util
from pathlib import Path

import httpx
import pytest

spec = importlib.util.spec_from_file_location(
    "verify_full_stack",
    Path(__file__).resolve().parents[2] / "tools/verify_full_stack.py",
)
verification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verification)


@pytest.mark.parametrize(
    "job",
    [
        {"status": "FAILED"},
        {
            "status": "DONE",
            "generation_before": "old",
            "generation_after": "old",
            "active_generation": "old",
        },
        {
            "status": "DONE",
            "generation_before": "old",
            "generation_after": "new",
            "active_generation": "old",
        },
        {"status": "DONE"},
    ],
)
def test_failed_or_unpublished_rebuild_never_passes(job):
    with (
        httpx.Client(
            base_url="http://test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=job)
            ),
        ) as client,
        pytest.raises(RuntimeError, match="Atomic rebuild"),
    ):
        verification.wait_rebuild(client, "job-id", 1)


def test_waits_for_requested_job_and_new_active_generation(monkeypatch):
    states = iter(
        [
            {"status": "PENDING"},
            {"status": "RUNNING"},
            {
                "status": "DONE",
                "generation_before": "old",
                "generation_after": "new",
                "active_generation": "new",
            },
        ]
    )

    def respond(request):
        assert request.url.path == "/api/v1/index/jobs/requested-job"
        return httpx.Response(200, json=next(states))

    monkeypatch.setattr(verification.time, "sleep", lambda seconds: None)
    with httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(respond)
    ) as client:
        assert verification.wait_rebuild(client, "requested-job", 1)["status"] == "DONE"


def test_rebuild_timeout_fails():
    with (
        httpx.Client(base_url="http://test") as client,
        pytest.raises(RuntimeError, match="did not finish"),
    ):
        verification.wait_rebuild(client, "job-id", 0)
