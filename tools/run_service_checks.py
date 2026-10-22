"""Use disposable Docker PostgreSQL/Redis; never touch an existing database or stack."""

import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
PY = Path(sys.executable)
OUT = ROOT / ".microservice-tests"
OUT.mkdir(exist_ok=True)
run_id = uuid4().hex[:10]
names = ["hybrid-check-pg-" + run_id, "hybrid-check-redis-" + run_id]
password = secrets.token_hex(24)


def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


pgport, rport = port(), port()


def docker(*args):
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        encoding="utf8",
        errors="replace",
        check=False,
    )


try:
    for name, image, args, env in [
        (
            names[0],
            "postgres:17-alpine",
            [],
            {
                "POSTGRES_PASSWORD": password,
                "POSTGRES_USER": "test_admin",
                "POSTGRES_DB": "hybrid_acceptance_test",
            },
        ),
        (names[1], "redis:8-alpine", ["redis-server", "--requirepass", password], {}),
    ]:
        command = [
            "run",
            "-d",
            "--name",
            name,
            "--label",
            "securedoc.purpose=hybrid-disposable-test",
            "-p",
            f"127.0.0.1:{pgport if name == names[0] else rport}:{5432 if name == names[0] else 6379}",
        ]
        for key, value in env.items():
            command += ["-e", f"{key}={value}"]
        result = docker(*command, image, *args)
        if result.returncode:
            raise RuntimeError(
                "Failed to create isolated test container: " + result.stderr[:300]
            )
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if (
            docker(
                "exec",
                names[0],
                "pg_isready",
                "-U",
                "test_admin",
                "-d",
                "hybrid_acceptance_test",
            ).returncode
            == 0
        ):
            break
        time.sleep(1)
    else:
        raise RuntimeError("Isolated PostgreSQL not ready")
    env = dict(os.environ)
    env.update(
        {
            "MICROSERVICES_TEST_DSN": f"host=127.0.0.1 port={pgport} dbname=hybrid_acceptance_test user=test_admin password={password}",
            "MICROSERVICES_TEST_REDIS_PASSWORD": password,
            "MICROSERVICES_TEST_REDIS_PORT": str(rport),
            "PYTHONIOENCODING": "utf8",
        }
    )
    report = OUT / "hybrid-pytest.xml"
    result = subprocess.run(
        [
            str(PY),
            "-m",
            "pytest",
            "microservices/tests",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={report}",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf8",
        errors="replace",
        check=False,
    )
    output = result.stdout + "\n" + result.stderr
    assert password not in output, "Unexpected credential in test output"
    (OUT / "hybrid-pytest.txt").write_text(output, encoding="utf8")
    print(output)
    print(
        json.dumps(
            {
                "run_id": run_id,
                "exit_code": result.returncode,
                "database": "isolated disposable PostgreSQL",
                "redis": "isolated disposable Redis",
                "cloud_calls": False,
            }
        )
    )
    if result.returncode:
        raise SystemExit(result.returncode)
    smoke = subprocess.run(
        [str(PY), str(ROOT / "tools/smoke_microservices.py")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf8",
        errors="replace",
        check=False,
    )
    smoke_output = smoke.stdout + "\n" + smoke.stderr
    if password in smoke_output:
        raise RuntimeError("Unexpected test credential in smoke output")
    (OUT / "hybrid-smoke.txt").write_text(smoke_output, encoding="utf8")
    print(smoke_output)
    raise SystemExit(smoke.returncode)
finally:
    for name in names:
        check = docker(
            "inspect",
            "--format",
            '{{ index .Config.Labels "securedoc.purpose" }}',
            name,
        )
        if check.returncode == 0 and check.stdout.strip() == "hybrid-disposable-test":
            docker("rm", "-f", "-v", name)
