"""Start three real HTTP processes against the disposable test database.

Verifies authentication, document queuing, chat history, and fail-closed authentication
after identity stops. Does not claim to test real S3/OpenSearch/LLM generation.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from psycopg.conninfo import conninfo_to_dict

ROOT = Path(__file__).resolve().parents[1]


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    info = conninfo_to_dict(os.environ["MICROSERVICES_TEST_DSN"])
    if not info.get("dbname", "").endswith("_test"):
        raise SystemExit("Smoke test requires a disposable _test database")
    ports = {s: port() for s in ("identity", "knowledge", "conversation")}
    processes = {}
    logs = []
    logdir = ROOT / ".microservice-tests" / "smoke"
    logdir.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(timeout=30)
    try:
        for service, service_port in ports.items():
            env = {
                **os.environ,
                "DB_HOST": info.get("host", "127.0.0.1"),
                "DB_PORT": info.get("port", "5432"),
                "DB_NAME": info["dbname"],
                "DB_USER": "svc_" + service,
                "DB_PASSWORD": "test-password-for-" + service,
                "AUTH_JWT_SECRET": "smoke-signing-key-" + "x" * 40,
                "KNOWLEDGE_SERVICE_TOKEN": "smoke-service-key-" + "x" * 40,
                "BOOTSTRAP_ADMIN_EMAIL": "smoke@test.local",
                "BOOTSTRAP_ADMIN_PASSWORD": "smoke-admin-password-1234",
                "IDENTITY_URL": f"http://127.0.0.1:{ports['identity']}",
                "KNOWLEDGE_URL": f"http://127.0.0.1:{ports['knowledge']}",
                "APP_ENVIRONMENT": "test",
                "CAPACITY_BACKEND": "memory",
                "LLM_MODEL": "smoke-model",
                "LLM_API_KEY": "smoke-key",
            }
            log = (logdir / (service + ".log")).open("w", encoding="utf-8")
            logs.append(log)
            processes[service] = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    service + "_service.app:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(service_port),
                ],
                cwd=ROOT / "microservices" / service,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        for service, listen in ports.items():
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    if (
                        client.get(
                            f"http://127.0.0.1:{listen}/ready", timeout=1
                        ).status_code
                        == 200
                    ):
                        break
                except httpx.RequestError:
                    pass
                if processes[service].poll() is not None:
                    raise RuntimeError(f"{service} exited; inspect {logdir}")
                time.sleep(0.25)
            else:
                raise RuntimeError(f"{service} did not become ready")
        urls = {s: f"http://127.0.0.1:{p}" for s, p in ports.items()}
        login = client.post(
            urls["identity"] + "/api/v1/auth/login",
            json={"email": "smoke@test.local", "password": "smoke-admin-password-1234"},
        )
        login.raise_for_status()
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        assert (
            client.get(
                urls["identity"] + "/api/v1/auth/me", headers=headers
            ).status_code
            == 200
        )
        name = f"smoke-{time.time_ns()}.txt"
        response = client.post(
            urls["knowledge"] + "/api/v1/documents/upload",
            headers=headers,
            files={"file": (name, ("Smoke content " + name).encode(), "text/plain")},
        )
        assert response.status_code == 201 and response.json()["status"] == "queued"
        assert (
            client.get(
                urls["conversation"] + "/api/v1/conversations", headers=headers
            ).status_code
            == 200
        )
        processes["conversation"].terminate()
        processes["conversation"].wait(timeout=10)
        assert (
            client.get(
                urls["knowledge"] + "/api/v1/documents", headers=headers
            ).status_code
            == 200
        )
        processes["identity"].terminate()
        processes["identity"].wait(timeout=10)
        assert client.get(urls["knowledge"] + "/health").status_code == 200
        assert (
            client.get(
                urls["knowledge"] + "/api/v1/documents", headers=headers
            ).status_code
            == 503
        )
        print(
            "PASS: three independent HTTP processes; login, document queue, chat history, and outage isolation."
        )
    finally:
        client.close()
        for process in processes.values():
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        for log in logs:
            log.close()


if __name__ == "__main__":
    main()
