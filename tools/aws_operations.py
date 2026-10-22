"""Export only allowlisted aggregate application metrics to CloudWatch Logs.

No docker logs or prompts are read. This is a one-shot async operations export;
application requests do not depend on CloudWatch availability.
"""

import argparse
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

from aws_finops import ROOT, Aws
from dotenv import dotenv_values

METRIC = re.compile(
    r'^(secure_doc_(?:finops_(?:enabled|available|calls|completed|reserved_microusd|input_tokens|output_tokens|usage_missing)|hybrid_circuit_open|admission_available|llm_active_slots|llm_slot_limit))(?:\{period="(day|month)"\})? ([0-9]+)$'
)


def run(*args):
    result = subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        encoding="utf8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Operations snapshot failed")
    return result.stdout


def snapshot():
    metadata = json.loads(
        (ROOT / ".microservice-tests/bedrock-stack-metadata.json").read_text()
    )
    ids = run(
        "docker",
        "ps",
        "--filter",
        "label=com.docker.compose.project=" + metadata["project"],
        "--filter",
        "label=com.docker.compose.service=conversation",
        "--format",
        "{{.ID}}",
    ).split()
    if len(ids) != 1:
        raise RuntimeError("Expected one verification conversation container")
    payload = run(
        "docker",
        "exec",
        ids[0],
        "python",
        "-c",
        "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/metrics',timeout=5).read().decode())",
    )
    counters = {}
    for line in payload.splitlines():
        match = METRIC.fullmatch(line)
        if match:
            name, period, value = match.groups()
            counters[name + ("_" + period if period else "")] = int(value)
    if counters.get("secure_doc_finops_enabled") != 1:
        raise RuntimeError("FinOps is not enabled in the live application")
    return {"version": 1, "kind": "aggregate_metrics_only", "metrics": counters}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    data = snapshot()
    out = ROOT / ".aws-local"
    out.mkdir(exist_ok=True)
    (out / "operations-snapshot.json").write_text(
        json.dumps(data, indent=2), encoding="utf8"
    )
    if args.apply:
        cfg = dotenv_values(ROOT / ".env.finops")
        aws = Aws(
            cfg.get("AWS_PROFILE") or "secure-doc-hybrid",
            cfg.get("AWS_REGION") or "ap-northeast-1",
        )
        group = "/securedoc/hybrid/operations"
        stream = "aggregate-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        aws.call(
            "logs",
            "create-log-stream",
            "--log-group-name",
            group,
            "--log-stream-name",
            stream,
        )
        event = {"timestamp": int(time.time() * 1000), "message": json.dumps(data)}
        with tempfile.TemporaryDirectory(prefix="securedoc-metrics-") as folder:
            p = Path(folder) / "event.json"
            p.write_text(json.dumps([event]), encoding="utf8")
            aws.call(
                "logs",
                "put-log-events",
                "--log-group-name",
                group,
                "--log-stream-name",
                stream,
                "--log-events",
                "file://" + p.as_posix(),
            )
        events = aws.call(
            "logs",
            "get-log-events",
            "--log-group-name",
            group,
            "--log-stream-name",
            stream,
        )["events"]
        if not any(json.loads(e["message"]) == data for e in events):
            raise RuntimeError("Uploaded aggregate event not found")
        data["cloudwatch_roundtrip_verified"] = True
        (out / "operations-snapshot.json").write_text(
            json.dumps(data, indent=2), encoding="utf8"
        )
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
