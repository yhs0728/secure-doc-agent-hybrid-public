# 800명 사용자·100명 동시 접속 확장 가이드

## 제공되는 기반

- 사용자별 LOCAL 로그인과 30분 JWT access token
- 워크스페이스 `VIEWER`, `EDITOR`, `ADMIN` 권한
- 기존 공유 API 키의 관리자 호환 모드
- 8GiB WSL 기준 API 1개, Worker 1개의 안전한 Compose 기본 replica
- Nginx gateway를 통한 API 부하 분산
- LLM 프로세스별 동시 처리 제한과 429 backpressure
- SQLAlchemy QueuePool의 pre-ping, recycle, LIFO 설정
- Prometheus 형식 `/metrics` endpoint
- 선택형 Prometheus/Grafana Compose profile
- Kubernetes API/Worker HPA 예시
- Locust 100명 부하 테스트 시나리오

## 사용자 생성과 로그인

초기 운영 관리자는 기존 API 키를 사용해 사용자를 생성할 수 있습니다.

```powershell
$adminHeaders = @{ Authorization = "Bearer $env:SECURE_DOC_API_KEY" }
$body = @{
  email = "user@example.com"
  display_name = "Example User"
  password = "replace-with-a-strong-password"
  workspace_role = "VIEWER"
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri http://localhost:8000/api/v1/auth/users `
  -Headers $adminHeaders -ContentType application/json -Body $body
```

로그인 후 반환된 access token을 Bearer token으로 사용합니다.

```powershell
$login = @{ email = "user@example.com"; password = "replace-with-a-strong-password" } | ConvertTo-Json
$token = (Invoke-RestMethod -Method Post `
  -Uri http://localhost:8000/api/v1/auth/login `
  -ContentType application/json -Body $login).access_token
```

역할 정책:

| 역할 | 조회·질문 | 업로드·삭제 | 인덱스 관리·사용자 생성 |
|---|---|---|---|
| VIEWER | 허용 | 거부 | 거부 |
| EDITOR | 허용 | 허용 | 거부 |
| ADMIN | 허용 | 허용 | 허용 |

Compose는 기본적으로 `ALLOW_LEGACY_API_KEY=false`이므로 공유 API 키 로그인을
차단합니다. 최초 관리자 bootstrap 때만 현재 셸에서 명시적으로 `true`로 설정하고,
관리자 로그인을 확인한 직후 다시 `false`로 되돌립니다.
초기 비밀번호로 로그인한 사용자는 `POST /api/v1/auth/change-password`에서 현재
비밀번호와 새 비밀번호를 전달해 즉시 교체할 수 있습니다.

## Compose 수평 확장

기본 replica 수는 8GiB WSL에서 API 1개, Worker 1개입니다. 운영 서버에서는 부하
테스트와 메모리 용량에 맞춰 확장합니다.

```powershell
$env:API_REPLICAS = "3"
$env:WORKER_REPLICAS = "1"
docker compose up -d --build
docker compose ps
```

API는 호스트 포트를 직접 사용하지 않고 Nginx gateway가 `localhost:8000`을 제공합니다. Worker는 PostgreSQL의 `SKIP LOCKED`와 lease를 사용하므로 여러 instance가 같은 작업을 동시에 처리하지 않습니다.

## LLM 동시 처리

`LLM_MAX_CONCURRENCY`는 API 프로세스 하나가 동시에 실행할 RAG 요청 수입니다. 슬롯이 `LLM_QUEUE_TIMEOUT_SECONDS` 안에 확보되지 않으면 API는 `429 LLM_CAPACITY_EXCEEDED`와 `Retry-After`를 반환합니다.

로컬 기본값은 API replica마다 1개입니다. 운영 환경에서 API replica가 3개이고 값을
4로 조정하면 애플리케이션 계층의 최대 실행 수는 12개입니다. 실제 LLM 서버가 그
처리량을 지원하는지는 별도 벤치마크가 필요합니다. 단일 RTX 2070 Ollama는 100개
동시 생성을 담당하는 구성으로 간주하면 안 됩니다.

## DB connection pool

각 프로세스는 SQLAlchemy QueuePool을 사용합니다.

```text
프로세스별 최대 연결 = DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW
전체 최대 연결 ≈ API replica와 Worker replica별 최대 연결의 합
```

PostgreSQL `max_connections`보다 충분히 낮게 유지해야 합니다. replica 수가 커지면 PgBouncer 같은 외부 transaction pooler를 PostgreSQL 앞에 배치하는 것이 권장됩니다.

## 모니터링

```powershell
$env:GRAFANA_ADMIN_PASSWORD = "replace-with-a-strong-password"
docker compose --profile monitoring up -d
```

- API metrics: `http://localhost:8000/metrics`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000` (Prometheus datasource 자동 연결)

`infra/prometheus-alerts.yml`에는 API 중단, 5xx/429 비율, p95 latency, DB pool
포화, Outbox/ingestion backlog, metrics 수집 실패 경보가 포함됩니다. 실제 알림 전송은
운영 환경의 Alertmanager 또는 Grafana contact point에 Slack, 이메일, PagerDuty 등을
연결해야 합니다.

## 100명 부하 테스트

운영 데이터가 아닌 별도 성능 시험 환경에서 실행합니다.

```powershell
python -m venv .venv-load
.\.venv-load\Scripts\python.exe -m pip install -r requirements-load.txt
$env:LOAD_TEST_TOKEN = "test-user-access-token"
.\.venv-load\Scripts\locust.exe -f tests/load/locustfile.py `
  --host http://localhost:8000 --users 100 --spawn-rate 10 --run-time 10m `
  --tags read --headless
```

`--tags read`는 문서 목록과 인덱스 상태처럼 일반 API의 100명 동시 접속을
검증합니다. RAG는 GPU/LLM 처리량을 별도로 측정해야 하므로 작은 사용자 수로 시작해
점진적으로 올립니다.

```powershell
.\.venv-load\Scripts\locust.exe -f tests/load/locustfile.py `
  --host http://localhost:8000 --users 2 --spawn-rate 1 --run-time 5m `
  --tags rag --headless
```

초기 합격 기준 예시:

- 일반 API p95 500ms 이하
- 전체 오류율 1% 미만
- 허용된 backpressure 외 5xx 0.1% 미만
- 작업 유실 0건
- 시험 종료 후 Outbox와 ingestion backlog 정상 소진

## Kubernetes 자동 확장

`infra/kubernetes/secure-doc-agent.yaml`에는 API 3~10개, Worker 2~8개 HPA가 포함됩니다. 적용 전 다음 준비가 필요합니다.

- `secure-doc-agent:latest`를 실제 registry image로 교체
- `secure-doc-secrets` Secret 생성
- 외부 PostgreSQL, S3, OpenSearch endpoint 설정
- Metrics Server 설치
- `ReadWriteMany`를 지원하는 StorageClass 준비
- 운영 ingress와 TLS 구성

`secure-doc-secrets`에는 최소한 `DATABASE_URL`, `API_ACCESS_KEY`, `AUTH_JWT_SECRET`,
`LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL`, Object Storage credential과 endpoint,
`OPENSEARCH_URL`을 준비합니다. 먼저 migration Job 완료를 확인한 뒤 API 트래픽을
열어야 합니다.

```bash
kubectl apply -f infra/kubernetes/secure-doc-agent.yaml
kubectl wait --for=condition=complete job/secure-doc-migrate --timeout=180s
kubectl get deployment,pods,hpa
```

HPA는 CPU와 메모리 기반의 시작점입니다. 실제 운영에서는 LLM queue depth와 ingestion backlog를 custom metric으로 노출해 확장 기준에 추가하는 것이 좋습니다.

## 검증된 로컬 처리량

2026-10-11에 8GiB WSL에서 API 3개와 Worker 2개를 일시 실행하고 읽기 전용
Locust 시나리오를 100명으로 1분간 수행했습니다. 총 1,860건, 실패 0건, 평균 8ms,
p95 23ms였고 Nginx는 각 API에 620건씩 분산했습니다. 이는 문서 목록과 인덱스 상태
조회 결과이며 RAG 생성 처리량을 의미하지 않습니다. 검증 후 로컬 구성은 API 1개와
Worker 1개로 복원했습니다.

2026-10-15에는 로컬 API 단일 프로세스와 100명 read 시나리오를 새 실행 스크립트로
1분간 검증했습니다. 총 1,903건, 실패 0건, 평균 10ms, p95 37ms였습니다. 같은 환경의
`qwen3:4b-instruct`를 예열한 뒤 2명 RAG 시나리오는 29건, 실패 0건, 평균 1.49초,
p95 3.3초였습니다. 예열 요청 자체는 약 7.7초였으므로 배포 직후 지연과 정상 상태
지연을 분리해서 관찰해야 합니다.
