> 이 문서는 분기 전 원본 기록입니다. 현재 실행 방법과 포트는 [DEPLOYMENT.md](DEPLOYMENT.md)를 따릅니다.

# SecureDoc Agent

현재 기본 구성은 **인증·사용자 / 문서·검색 / 대화·RAG의 마이크로서비스**입니다.
서비스별 이미지·의존성·마이그레이션·DB 계정을 분리하고 HTTP v1 계약으로 통신합니다.
PostgreSQL 서버 하나의 전용 스키마를 사용하며 서비스 간 DB 직접 접근은 차단합니다.

```powershell
.\.venv\Scripts\python.exe tools/prepare_microservices_env.py
docker compose --env-file .env.microservices up -d --build
```

자세한 변경 이유·개별 패치·데이터 이관·롤백은 [마이크로서비스 운영 가이드](docs/microservices.md),
서비스 소유권과 API 계약은 [서비스 구성](microservices/README.md)을 참고하세요.
아래 기존 backend 설명과 운영 명령은 **레거시 구현**의 기록입니다. 레거시 실행은
`docker compose -f compose.legacy.yaml --env-file .env up -d --build`를 사용합니다.
새 환경은 별도 `micro_*` 볼륨을 사용하며 기존 데이터는 이관 도구로 옮겨야 합니다.

SecureDoc Agent는 조직과 워크스페이스 단위로 문서를 안전하게 수집하고, 검색 증강 생성(RAG)으로 근거가 포함된 답변을 제공하는 풀스택 서비스입니다.

현재 기본 배포 구성은 PostgreSQL을 원본 상태 저장소로 사용하고, S3 호환 Object Storage에 원본 파일을 저장하며, OpenSearch에 검색 인덱스를 구성합니다. API와 Worker 사이의 비동기 작업은 PostgreSQL 작업 큐와 Transactional Outbox로 처리합니다.

## 현재 구현 상태

- TXT, PDF, DOCX, CSV 업로드 및 API 본문 수집
- 문서 분할, MiniLM 임베딩, RAG 검색과 출처 반환
- Organization → Workspace → Document 멀티테넌트 구조
- 사용자별 LOCAL 로그인, JWT access token, VIEWER/EDITOR/ADMIN 권한
- SQLAlchemy 2.x ORM과 Alembic 마이그레이션
- PostgreSQL RLS(Row-Level Security)
- S3 호환 원본 저장소와 SHA-256 무결성 확인
- Transactional Outbox 기반 업로드·삭제 일관성 처리
- OpenSearch physical index 생성 후 alias 원자적 교체
- 다중 Worker 작업 선점, lease 복구, advisory lock
- 8GiB WSL에서는 API 1개·Worker 1개를 기본으로 사용하며 환경변수로 수평 확장 가능
- LLM 동시 처리 제한과 429 backpressure
- Prometheus 메트릭과 Kubernetes HPA 예시
- 채팅 세션, 메시지, 인용 기록 영속화
- Docker Compose 헬스 체크와 readiness 검증
- 애플리케이션 소유 FAISS 어댑터와 로컬 Object Storage fallback 지원
- Prometheus 알람 규칙 8개와 Grafana Prometheus datasource 자동 구성
- Alertmanager 연동과 localhost 전용 운영 포트
- 운영 모드 보안 설정 검증과 OpenSearch CA 인증서 지원
- PostgreSQL·Object Storage checksum 백업/복구 자동화
- 반복 가능한 read/RAG Locust 부하 시험과 HTML·CSV 결과 저장
- React 기반 Evidence Workspace, 문서·인덱스·사용자 관리 UI
- 데스크톱 3열 근거 검증 화면과 모바일 근거 Dialog

마지막 백엔드 자동 테스트 결과는 `164 passed, 3 skipped`이며, 프론트엔드는 단위
테스트 `2 passed`, Playwright 사용자 흐름 `3 passed`입니다. 별도의 실제 MiniLM·Ollama
E2E 테스트도 `3 passed`입니다.

## 저장소 구조

```text
secure-doc-agent/
├─ backend/       # FastAPI, RAG, Worker, DB migration, Python tests
├─ frontend/      # React SPA, UI tests, frontend Nginx image
├─ infra/         # Kubernetes, Prometheus, Grafana, Alertmanager, systemd
├─ compose.yaml   # 로컬 통합 실행
└─ .env.example   # 통합 실행 환경변수 예시
```

백엔드와 프론트엔드는 각각 독립적인 build context와 테스트 명령을 사용합니다.

## 아키텍처

```text
Windows
└─ WSL2 Ubuntu
   └─ Docker Compose
      ├─ Nginx gateway + React 정적 배포
      ├─ API × 1 (운영 권장 시작점 3+)
      ├─ Worker × 1 (운영 권장 시작점 2+)
      ├─ PostgreSQL 17
      ├─ SeaweedFS S3 API
      ├─ OpenSearch 3.3.2
      └─ Prometheus + Grafana (선택적 monitoring profile)

문서 업로드
→ PostgreSQL 트랜잭션
→ Outbox 이벤트
→ Worker
→ S3 원본 저장
→ 문서 파싱·임베딩
→ OpenSearch 인덱스 생성
→ alias 교체
→ 문서 READY
```

PostgreSQL이 문서 상태, 작업, Outbox, 채팅 기록의 Source of Truth입니다. 외부 저장소 호출은 DB 트랜잭션에 직접 포함하지 않고 재시도 가능한 Outbox 이벤트로 전달합니다.

## 기술 스택

| 영역 | 기술 |
|---|---|
| API | Python 3.12, FastAPI, Uvicorn |
| RAG | LangGraph, LangChain Core, Sentence Transformers |
| ORM·마이그레이션 | SQLAlchemy 2.x, Alembic |
| 데이터베이스 | PostgreSQL 17 |
| 검색 | OpenSearch 3.3.2, 애플리케이션 소유 FAISS fallback |
| Object Storage | S3 API, SeaweedFS 로컬 구성 |
| LLM | OpenAI 호환 API 또는 Ollama |
| Web | React 19, TypeScript, Vite, TanStack Query, Tailwind CSS 4 |
| UI 검증 | Vitest, Testing Library, Playwright |
| 배포 | Docker Compose on WSL2 |

## 실행 환경

- Windows 10/11과 Docker Desktop 또는 WSL2 Ubuntu
- Docker Compose v2
- Python 3.12 컨테이너
- Ollama 또는 OpenAI 호환 LLM endpoint
- 최초 실행 시 Hugging Face 임베딩 모델 다운로드를 위한 네트워크 또는 사전 캐시

현재 애플리케이션 컨테이너는 CPU 전용 PyTorch를 사용합니다. Windows GPU는 WSL에서 인식되지만 컨테이너 임베딩에는 아직 할당하지 않았습니다.

## Docker Compose 실행

프로젝트 루트의 `.env`에 PostgreSQL, Object Storage, API, LLM 관련 값을 준비해야 합니다. 비밀번호와 API 키는 저장소에 커밋하지 마세요.

WSL에서 실행하는 경우:

```bash
cd /mnt/c/llm-study/secure-doc-agent/hybrid
docker compose up -d --build
docker compose ps
```

Windows PowerShell에서 상태를 확인합니다.

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/health
Invoke-RestMethod http://localhost:8000/api/v1/ready
```

정상 readiness 응답:

```json
{
  "status": "ready",
  "checks": {
    "application": "ready",
    "postgresql": "ready",
    "object_storage": "ready",
    "opensearch": "ready"
  }
}
```

서비스 포트:

| 서비스 | 주소 |
|---|---|
| Web app + API gateway | `http://localhost:8000` |
| PostgreSQL | `localhost:5432` |
| S3 API | `http://localhost:9000` |
| OpenSearch | `http://localhost:9200` |
| OpenSearch Performance Analyzer | `localhost:9600` |
| Prometheus | `http://localhost:9090` (`monitoring` profile) |
| Grafana | `http://localhost:3000` (`monitoring` profile) |

로그와 종료:

```bash
docker compose logs --tail 100 api
docker compose logs --tail 100 worker
docker compose down
```

`docker compose down`은 컨테이너와 네트워크만 내립니다. 영속 볼륨을 삭제하는 `down -v`는 저장 데이터를 모두 제거하므로 주의해야 합니다.

## 프론트엔드 로컬 실행

Node.js 22 환경에서 API와 별도로 UI를 개발할 수 있습니다. Vite 개발 서버는
`/api` 요청을 `http://localhost:8000`으로 전달합니다.

```powershell
cd frontend
npm ci
npm run dev
```

검증 명령은 다음과 같습니다.

```powershell
npm run typecheck
npm run test
npm run build
npm run test:e2e
npm audit
```

프론트엔드 구조와 현재 API 제약은 [`frontend/README.md`](frontend/README.md)에 정리되어 있습니다.

## 로컬 Python 실행

Docker 없이 애플리케이션 코드와 테스트를 실행할 수 있습니다.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

필요한 환경변수를 현재 PowerShell 세션 또는 프로젝트 루트의 `.env`에 설정한 뒤 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app `
  --host 127.0.0.1 --port 8000 --workers 1
```

로컬 fallback 모드는 `DATABASE_ENABLED=false`, `OBJECT_STORAGE_BACKEND=LOCAL`, `SEARCH_BACKEND=FAISS` 조합을 지원합니다. 운영형 구성은 Docker Compose의 PostgreSQL, S3 API, OpenSearch 조합을 사용합니다.

FAISS fallback은 `langchain-community`에 의존하지 않고 저장소 내부 어댑터를 사용합니다. 기존 LangChain FAISS의 `index.faiss`와 `index.pkl` 스냅샷도 계속 읽을 수 있습니다.

## Ollama 연결

Windows에서 Ollama를 사용하는 경우:

```powershell
ollama pull qwen3:4b-instruct
ollama serve
Invoke-RestMethod http://localhost:11434/api/tags
```

Docker Desktop을 사용하면 컨테이너는 기본적으로
`http://host.docker.internal:11434/v1` 경로로 Windows Ollama에 접근합니다. WSL
내부에 Docker Engine을 직접 설치한 구성에서는 `host.docker.internal` 프록시가
자동 제공되지 않습니다. 이 프로젝트는 `host-gateway` mapping을 추가하므로 WSL
Ollama를 Docker bridge인 `172.17.0.1:11434`에 바인딩하면 동일한 URL을 사용할 수
있습니다. Ollama의 GPU 사용과 컨테이너 내부 임베딩의 CPU 사용은 서로 독립적입니다.

WSL systemd에서 영구 바인딩하려면 저장소의 drop-in 설정을 설치합니다.

```bash
sudo install -D -m 0644 \
  infra/systemd/ollama-secure-doc-agent.conf \
  /etc/systemd/system/ollama.service.d/secure-doc-agent.conf
sudo systemctl daemon-reload
sudo systemctl restart ollama
curl http://172.17.0.1:11434/api/tags
```

Compose는 `.env`의 `LLM_BASE_URL=http://host.docker.internal:11434/v1`과
`LLM_TIMEOUT_SECONDS`를 API·Worker에 전달합니다. 첫 모델 로딩은 시간이 걸릴 수
있으므로 로컬 GPU 환경의 기본 예시는 300초입니다.

## API 사용

인증이 필요한 endpoint는 로그인으로 발급받은 JWT Bearer token을 사용합니다. 기존
`API_ACCESS_KEY`는 bootstrap 또는 비상 복구 시에만 사용하는 관리자 호환 인증이며,
Compose 기본값인 `ALLOW_LEGACY_API_KEY=false`에서는 비활성화됩니다.

```http
Authorization: Bearer <JWT_ACCESS_TOKEN>
```

주요 endpoint:

| Method | Endpoint | 설명 | 인증 |
|---|---|---|---|
| GET | `/api/v1/health` | API 프로세스 상태 | 없음 |
| GET | `/api/v1/ready` | 외부 의존성 준비 상태 | 없음 |
| POST | `/api/v1/auth/login` | 사용자 로그인과 JWT 발급 | 없음 |
| GET | `/api/v1/auth/me` | 현재 사용자와 역할 조회 | Bearer |
| POST | `/api/v1/auth/change-password` | 현재 사용자 비밀번호 변경 | Bearer |
| POST | `/api/v1/auth/users` | 워크스페이스 사용자 생성 | ADMIN |
| GET | `/api/v1/documents` | 문서 목록과 검색 | VIEWER 이상 |
| GET | `/api/v1/documents/{document_id}` | 문서 상세 | VIEWER 이상 |
| POST | `/api/v1/documents/upload` | 파일 업로드 | EDITOR 이상 |
| POST | `/api/v1/documents/ingest` | JSON 문서 수집 | EDITOR 이상 |
| DELETE | `/api/v1/documents/{document_id}` | 문서 삭제 요청 | EDITOR 이상 |
| POST | `/api/v1/questions` | RAG 질문 | VIEWER 이상 |
| POST | `/api/v1/index/update` | 인덱스 갱신 | ADMIN |
| GET | `/api/v1/index/status` | 인덱스 상태 | VIEWER 이상 |

파일 업로드 예시:

```powershell
curl.exe -X POST http://localhost:8000/api/v1/documents/upload `
  -H "Authorization: Bearer $env:SECURE_DOC_API_KEY" `
  -F "file=@backend/data/source/security-policy.txt"
```

질문 예시:

```powershell
$headers = @{ Authorization = "Bearer $env:SECURE_DOC_API_KEY" }
$body = @{ question = "비밀번호 변경 주기는 어떻게 되나요?" } | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri http://localhost:8000/api/v1/questions `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

오류 응답은 공통 envelope와 `request_id`를 사용합니다.

```json
{
  "error": {
    "code": "LLM_TIMEOUT",
    "message": "LLM 서버 응답 시간이 초과되었습니다.",
    "request_id": "9e4a..."
  }
}
```

## 데이터베이스와 마이그레이션

마이그레이션과 기본 tenant bootstrap은 Compose의 `migrate` 서비스가 API와 Worker 시작 전에 자동으로 실행합니다.

수동 확인 명령:

```powershell
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m database.verify
.\.venv\Scripts\python.exe -m database.verify_operations
```

현재 마이그레이션:

```text
0001_initial_schema
0002_outbox_delivery
```

스키마는 identity, content, rag, chat, ops의 다섯 영역으로 나뉩니다. 상세 ERD와 관계는 [PostgreSQL ERD](backend/docs/postgresql-erd.md)를 참고하세요.

## Outbox와 동시성

- 업로드와 삭제 요청은 도메인 상태 및 Outbox 이벤트와 같은 DB 트랜잭션에 기록됩니다.
- Worker는 `FOR UPDATE SKIP LOCKED`로 작업을 선점합니다.
- 실패한 작업은 지수 backoff로 재시도합니다.
- 비정상 종료로 남은 작업은 lease 만료 후 회수합니다.
- workspace별 PostgreSQL advisory lock으로 동시 인덱스 갱신을 직렬화합니다.
- OpenSearch는 새 physical index 검증 후 alias를 한 번에 교체합니다.

운영 절차와 장애 확인 SQL은 [운영 배포 가이드](backend/docs/operations.md)를 참고하세요.

## 테스트

빠른 자동 테스트는 실제 LLM을 호출하지 않습니다.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

실제 MiniLM, 검색 저장소, LLM을 연결하는 E2E 테스트:

```powershell
$env:RUN_REAL_E2E = "1"
$env:HF_HUB_OFFLINE = "1" # 임베딩 모델이 이미 캐시된 경우
.\.venv\Scripts\python.exe -m pytest tests/e2e/test_real_e2e.py -v -s
Remove-Item Env:RUN_REAL_E2E
```

RAG 평가:

```powershell
.\.venv\Scripts\python.exe -m evaluation.evaluate_rag --retrieval-only
.\.venv\Scripts\python.exe -m evaluation.evaluate_rag
```

최근 스모크 테스트에서는 health/readiness, 미인증 요청 거부, 문서 등록·조회·인덱싱,
RAG 답변과 citation, metrics, 문서 삭제 흐름을 확인했습니다. 마지막 문서 삭제로 인덱스가
비는 경우도 회귀 테스트에 포함되어 있습니다.

Locust 부하 테스트는 별도의 시험 환경에서 실행합니다.

```powershell
python -m venv .venv-load
.\.venv-load\Scripts\python.exe -m pip install -r requirements-load.txt
$env:LOAD_TEST_TOKEN = "test-user-access-token"

.\scripts\run_load_test.ps1 -Scenario read -Users 100 -SpawnRate 10 -RunTime 10m
```

2026-10-15 로컬 1분 스모크 결과는 100명 read 시나리오 1,903건에서 p95 37ms·실패
0건이었고, Ollama를 예열한 2명 RAG 시나리오 29건에서 p95 3.3초·실패 0건이었습니다.
첫 RAG 예열 요청은 별도로 약 7.7초가 걸렸습니다. 이 수치는 로컬 시험 결과이며 운영
용량 보장을 의미하지 않습니다. 상세 기준은 [확장 가이드](backend/docs/scaling.md)를 참고하세요.

## 모니터링

```powershell
$env:GRAFANA_ADMIN_PASSWORD = "replace-with-a-strong-password"
docker compose --profile monitoring up -d
```

Prometheus는 15초마다 API의 `/metrics`를 수집하고 경보를 Alertmanager로 전달합니다.
Grafana와 Alertmanager는 localhost에만 노출됩니다. 노출 지표는 다음과 같습니다.

- HTTP 요청 수(`method`, `path`, `status`)와 처리 중 요청 수
- HTTP 응답시간 histogram
- DB pool checked-in/out, overflow, capacity
- Outbox와 ingestion job backlog
- 의존 시스템 metrics 수집 성공 여부

기본 알람 트리거:

| 알람 | 조건 | 지속 시간 | 심각도 |
|---|---|---:|---|
| API target down | API job의 모든 target이 down | 1분 | critical |
| High server error rate | 5xx 비율 1% 초과 | 5분 | critical |
| High backpressure rate | 429 응답이 초당 0.1건 초과 | 5분 | warning |
| High p95 latency | p95 응답시간 2초 초과 | 5분 | warning |
| DB pool near capacity | pool 사용률 80% 초과 | 5분 | warning |
| Outbox backlog | 미처리 Outbox가 존재 | 10분 | warning |
| Ingestion backlog | 미완료 ingestion job이 존재 | 10분 | warning |
| Metrics collection failed | 의존 시스템 지표 조회 실패 | 2분 | critical |

Grafana에는 Prometheus datasource가 자동 등록됩니다. 기본 Alertmanager receiver는 경보를
외부로 전송하지 않습니다. 실제 Slack·이메일·PagerDuty endpoint는 조직의 승인된 주소와
credential을 배포 환경의 Alertmanager 설정에 추가해야 합니다.

## 운영 시 주의사항

- 로컬 OpenSearch는 단일 노드이며 security plugin이 비활성화되어 있습니다. 외부 공개 환경에서는 인증과 TLS를 활성화해야 합니다.
- `APP_ENVIRONMENT=production`은 외부 저장소 암호화, OpenSearch HTTPS·인증서 검증, 강한 JWT/API key와 legacy 인증 비활성화를 강제합니다.
- 비밀번호, API 키, Object Storage credential을 Git에 커밋하지 마세요.
- readiness가 실패하면 트래픽을 보내기 전에 PostgreSQL, Object Storage, OpenSearch 상태를 확인하세요.
- `backend/scripts/backup.ps1`로 PostgreSQL과 원본 Object Storage를 백업하고 `backend/scripts/restore.ps1`로 별도 환경에서 정기 복구 시험을 수행하세요. OpenSearch는 복구 후 재구축합니다.
- 현재 Docker 이미지는 CPU 전용 PyTorch를 사용합니다. CUDA 전환에는 CUDA PyTorch, NVIDIA Container Toolkit, Compose GPU 할당이 모두 필요합니다.
- `/metrics`에는 HTTP, DB pool, Outbox와 ingestion backlog 지표가 노출됩니다. 외부 공개 환경에서는 gateway 또는 네트워크 정책으로 접근을 제한하세요.

## 관련 문서

- [백엔드 실행과 구조](backend/README.md)
- [프론트엔드 실행과 구조](frontend/README.md)
- [PostgreSQL ERD와 스키마](backend/docs/postgresql-erd.md)
- [운영 배포와 장애 대응](backend/docs/operations.md)
- [백엔드 MVP 검증 설계](backend/docs/backend-mvp-verification.md)
- [800명 사용자·100명 동시 접속 확장 가이드](backend/docs/scaling.md)
