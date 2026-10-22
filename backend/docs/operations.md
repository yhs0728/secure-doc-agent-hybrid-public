# 운영 배포와 일관성 검증

## 구성

운영 구성은 다음 다섯 프로세스로 분리됩니다.

| 구성 요소 | 역할 | 기준 데이터 |
|---|---|---|
| API | 업로드, 조회, 질문, 삭제 요청 | PostgreSQL |
| Worker | Outbox 발행, 문서 파싱, 인덱스 갱신 | PostgreSQL 작업 큐 |
| PostgreSQL | 문서 상태, 작업, Outbox, 채팅 기록 | Source of Truth |
| S3 호환 저장소 | 원본 문서 바이너리 | `content.storage_objects`로 추적 |
| OpenSearch | 검색 본문과 임베딩 | 재구축 가능한 파생 데이터 |

## Outbox 처리 순서

업로드 API는 문서·버전·저장 객체·ingestion job과 `OBJECT_UPLOAD_REQUESTED`
이벤트를 하나의 PostgreSQL 트랜잭션에 기록합니다. 따라서 DB 반영과 이벤트 생성 중
하나만 성공하는 상태가 생기지 않습니다.

1. Worker가 `FOR UPDATE SKIP LOCKED`로 이벤트를 선점합니다.
2. 원본을 S3 호환 저장소에 올리고 SHA-256 metadata를 다시 확인합니다.
3. 성공하면 같은 이벤트를 `PUBLISHED`로 바꾸고 ingestion job을 `PENDING`으로
   활성화합니다.
4. 실패하면 오류와 재시도 시각을 기록하고 지수 backoff로 재시도합니다.
5. Worker가 비정상 종료되어 `PROCESSING`에 남은 이벤트는 lease 만료 후 회수합니다.

Object Storage API는 본질적으로 DB 트랜잭션에 참여하지 않으므로 정확히 한 번 실행을
가정하지 않습니다. 대신 고정 object key, event dedupe key, 검증 가능한 checksum을
사용해 재실행해도 같은 최종 상태가 되도록 설계했습니다.

삭제도 같은 방식입니다. 먼저 문서를 `DELETING`으로 전환하고 Outbox 이벤트를 만든 뒤,
외부 객체 삭제가 성공하면 `DELETED`로 확정합니다. 일시 장애가 나면 문서는 삭제 중
상태로 남아 worker가 재시도합니다.

## 다중 프로세스 안전성

- Outbox와 ingestion job: 행 잠금과 `SKIP LOCKED`로 한 작업을 한 worker만 선점합니다.
- 비정상 종료로 `RUNNING`/`PROCESSING`에 남은 작업은 lease 만료 후 재시도 상태로
  자동 회수합니다.
- 검색 인덱스 갱신: workspace별 PostgreSQL advisory lock으로 API와 여러 worker 사이의
  동시 갱신을 직렬화합니다.
- OpenSearch 게시: 새 physical index를 완성하고 문서 수를 검증한 뒤 alias를 한 번에
  교체합니다. 실패한 build는 활성 alias에 노출되지 않습니다.
- 모든 OpenSearch 검색은 `workspace_id` 필터를 강제로 포함합니다.

## Docker Compose 배포

프로젝트 루트의 `.env`에 PostgreSQL, Object Storage, API 및 LLM 설정을 준비하고 모든 secret을 안전한 값으로 지정합니다.
PostgreSQL 비밀번호를 URL 특수문자 없이 만들거나 URL encoding 해야 합니다.
API와 worker는 업로드 staging 경로를 공유해야 합니다. Compose는
`secure_doc_source` volume을 사용하며, 여러 호스트로 확장할 때도 이 경로는
공유·내구성 volume이어야 합니다.
임베딩 모델은 `secure_doc_model_cache` volume에 저장해 API와 worker가 공유하고
컨테이너 재생성 시에도 다시 다운로드하지 않습니다.
Compose의 로컬 S3 서비스는 공개 이미지가 유지되는 SeaweedFS 단일 노드 모드를
사용하며 호스트의 `9000` 포트로 노출합니다. 애플리케이션의 `MINIO` 설정값은
MinIO 전용 SDK가 아니라 표준 S3 API endpoint를 뜻합니다.
로컬 OpenSearch도 단일 노드이므로 `OPENSEARCH_NUMBER_OF_REPLICAS=0`을 사용합니다.
다중 노드 운영 환경에서는 복제본 수를 클러스터 정책에 맞춰 늘립니다.

```powershell
docker compose up -d --build
docker compose ps
Invoke-RestMethod http://localhost:8000/api/v1/health
Invoke-RestMethod http://localhost:8000/api/v1/ready
```

`health`는 API 프로세스 생존만 확인하고 `ready`는 설정에 따라 PostgreSQL, Object
Storage, OpenSearch까지 확인합니다. `ready`가 503이면 트래픽을 보내지 않아야 합니다.

## 검증 명령

다음 Python 명령은 저장소의 `backend` 디렉터리에서 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m database.verify
.\.venv\Scripts\python.exe -m database.verify_operations
.\.venv\Scripts\python.exe -m database.worker --once
.\.venv\Scripts\python.exe -m pytest -q
```

`database.verify_operations`는 migration/RLS 구조와 별도 Python 프로세스 두 개가 같은
advisory lock 임계 구역에 동시에 들어가지 않는지를 실제 PostgreSQL 연결로 검사합니다.

실제 MiniLM과 로컬 Ollama까지 포함한 E2E는 애플리케이션 백엔드를 임시 디렉터리로
격리하므로 개발·운영 데이터베이스에 접근하지 않습니다.

```powershell
$env:RUN_REAL_E2E = "1"
$env:HF_HUB_OFFLINE = "1" # 모델이 이미 캐시된 경우
.\.venv\Scripts\python.exe -m pytest tests/e2e/test_real_e2e.py -v -s
```

## 운영 보안 게이트

`APP_ENVIRONMENT=production`이면 애플리케이션 시작 전에 다음 조건을 강제합니다.

- PostgreSQL, 외부 Object Storage, OpenSearch 사용
- JWT와 API key에 32자 이상의 값 사용 및 legacy API key 인증 비활성화
- Object Storage 암호화 연결
- OpenSearch HTTPS, 전용 계정, 인증서 검증 및 필요 시 CA bundle 지정

Kubernetes 예시는 `secure-doc-secrets`와 `secure-doc-opensearch-ca` Secret이 이미
생성되어 있다고 가정합니다. 비밀값과 CA 인증서는 manifest나 Git에 넣지 않습니다.

## 백업과 복구

PostgreSQL과 원본 Object Storage가 복구의 기준입니다. OpenSearch는 파생 데이터이므로
복구 후 ingestion 작업으로 재구축합니다. 백업은 파일별 SHA-256 manifest를 함께 만들고
기본 14일보다 오래된 백업을 정리합니다.

```powershell
.\scripts\backup.ps1 -Destination backups -RetentionDays 14
```

복구는 API·worker·gateway를 일시 중지하고 현재 데이터를 덮어쓰므로 명시적인 `-Force`가
필요합니다. 별도 환경에서 정기적으로 복구 리허설을 수행한 뒤 readiness와 문서 검색을
확인합니다.

```powershell
.\scripts\restore.ps1 -BackupDirectory backups\20261015-020000 -Force
.\.venv\Scripts\python.exe -m database.verify
Invoke-RestMethod http://localhost:8000/api/v1/ready
```

## 알림과 부하 검증

`monitoring` profile은 Prometheus 경보를 Alertmanager에 전달합니다. 저장소 기본 receiver는
외부 전송을 하지 않으므로 배포 환경에서 승인된 webhook·메일·PagerDuty receiver를
별도 설정으로 추가해야 합니다. Alertmanager와 Grafana 포트는 localhost에만 공개됩니다.

```powershell
$env:GRAFANA_ADMIN_PASSWORD = "<strong-password>"
docker compose --profile monitoring up -d
Invoke-RestMethod http://localhost:9093/-/ready
```

부하 시험 결과는 저장소 루트의 `load-results/` 아래 CSV와 HTML로 저장됩니다.

```powershell
$env:LOAD_TEST_TOKEN = "<viewer-access-token>"
.\scripts\run_load_test.ps1 -Scenario read -Users 100 -SpawnRate 10 -RunTime 10m
.\scripts\run_load_test.ps1 -Scenario rag -Users 10 -SpawnRate 1 -RunTime 5m
```

## 장애 확인

```sql
SELECT id, event_type, status, attempt_count, max_attempts,
       available_at, locked_by, error_message
FROM ops.outbox_events
WHERE status <> 'PUBLISHED'
ORDER BY created_at;

SELECT id, job_type, status, attempt_count, max_attempts,
       available_at, locked_by, error_message
FROM rag.ingestion_jobs
WHERE status NOT IN ('SUCCEEDED', 'CANCELLED')
ORDER BY created_at;
```

최대 시도 횟수를 소진한 이벤트는 자동 재시도 대상에서 빠집니다. 원인을 해결한 뒤
운영자가 `attempt_count`, `available_at`, 상태를 검토해 재처리해야 합니다. 객체나 검색
인덱스를 직접 삭제하기 전에 PostgreSQL의 참조 상태와 활성 alias를 먼저 확인합니다.
