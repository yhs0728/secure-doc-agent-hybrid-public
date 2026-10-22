import os

from locust import HttpUser, between, tag, task


class SecureDocUser(HttpUser):
    wait_time = between(1, 5)

    def on_start(self) -> None:
        token = os.getenv("LOAD_TEST_TOKEN") or os.getenv("API_ACCESS_KEY")
        email = os.getenv("LOAD_TEST_EMAIL")
        password = os.getenv("LOAD_TEST_PASSWORD")
        if not token and email and password:
            response = self.client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": password},
                name="POST /api/v1/auth/login",
            )
            response.raise_for_status()
            token = response.json()["access_token"]
        if not token:
            raise RuntimeError(
                "LOAD_TEST_TOKEN 또는 LOAD_TEST_EMAIL/LOAD_TEST_PASSWORD가 필요합니다."
            )
        self.headers = {"Authorization": f"Bearer {token}"}

    @task(6)
    @tag("read")
    def list_documents(self) -> None:
        self.client.get(
            "/api/v1/documents",
            headers=self.headers,
            name="GET /api/v1/documents",
        )

    @task(2)
    @tag("read")
    def index_status(self) -> None:
        self.client.get(
            "/api/v1/index/status",
            headers=self.headers,
            name="GET /api/v1/index/status",
        )

    @task(1)
    @tag("rag")
    def ask_question(self) -> None:
        self.client.post(
            "/api/v1/questions",
            headers=self.headers,
            json={"question": "원격 접속 보안 정책을 요약해 주세요."},
            name="POST /api/v1/questions",
        )
