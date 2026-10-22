# SecureDoc 서비스 경계

기본 실행은 루트 `compose.yaml`입니다. 기존 `backend/`는 데이터 이관·롤백을 위한
레거시이며 새 서비스 이미지에는 포함되지 않습니다.

| 서비스 | 소유 코드·데이터 | 외부 접근 |
|---|---|---|
| identity | `identity/`, `ms_identity`, 사용자·워크스페이스·권한·비밀번호 | 자기 PostgreSQL 스키마 |
| knowledge | `knowledge/`, `ms_knowledge`, 문서·원본·처리 큐·색인 | identity HTTP, S3, OpenSearch |
| conversation | `conversation/`, `ms_conversation`, 대화·메시지·인용 스냅샷·RAG | identity HTTP, knowledge HTTP, LLM, Redis 공통 제어 |

Knowledge API와 Worker는 같은 업무 서비스의 두 실행 역할입니다. 둘은 자기 큐를
공유하지만 다른 업무 서비스의 DB에는 접근하지 않습니다. 검색과 문서는 한 서비스가
소유하므로 별도 메시지 브로커 없이 PostgreSQL의 내구성 작업 큐로 원본 저장과 색인을
재시도할 수 있습니다. 대화 서비스는 임베딩·파서·OpenSearch·S3 라이브러리를 설치하지 않습니다.

각 폴더는 독립 Docker build context, 버전을 고정한 requirements, migration, 앱 진입점을 가집니다.
서비스 로컬 `platform.py`는 개별 소유하는 작은 인프라 코드입니다. 실행 중 sibling 폴더나
공유 ORM을 import하지 않습니다. RAG 그래프는 conversation이 소유하는 독립 소스로
옮겼으며 이후 backend 원본 변경이 새 서비스에 자동 반영되지 않습니다.

서비스별 `001_*.sql`, `002_*.sql`은 한번 적용하면 수정하지 않고 다음 번호 파일로
변경합니다. 시작 시 자기 스키마에서 advisory lock을 획득하고 미적용 파일만 실행합니다.
동시 시작하는 Worker/API가 같은 migration을 중복 실행하지 않습니다.

## API 계약 v1

외부 URL은 기존 UI와 같습니다. Gateway가 auth → identity, documents/index → knowledge,
questions/conversations → conversation으로 라우팅합니다. 요청 ID를 전달하고 내부 경로와
metrics는 공개하지 않습니다. 각 서비스 OpenAPI는 컨테이너 내부 `/openapi.json`입니다.

- `GET identity/api/v1/auth/me`: Bearer 검증 및 최신 사용자·워크스페이스·역할 확인.
  다른 서비스는 JWT 서명 키나 사용자 DB 계정을 갖지 않습니다. 인증 서비스가 불가하면
  503으로 차단합니다. 권한 변경은 다음 요청부터 반영됩니다. 이 선택은 인증 서비스의
  가용성·지연 시간에 의존합니다. 트래픽이 커지면 RS256/JWKS + 짧은 TTL의 권한 투영을
  별도 변경으로 도입할 수 있습니다.
- `POST knowledge/internal/v1/search`: Bearer + `X-Service-Key` 모두 필요.
  입력 `{"query":"...","k":3}`, 출력 `{"version":1,"chunks":[...]}`.
  chunk에는 `document_id`, `source`, `chunk_id`, `text`, `page`, `score`가 있습니다.
- `POST knowledge/internal/v1/documents/validate`: 동일 인증. 입력 `document_ids` 배열,
  출력 `{"version":1,"document_ids":[현재 READY 문서 ID]}`. 생성 후 삭제 여부를 재확인합니다.
  생성 완료와 사용자 수신 사이의 삭제까지 원자적으로 막는 분산 트랜잭션은 아닙니다.
- 업로드는 201 + `status=queued`, 재색인은 202 + `status=queued`입니다.
  문서 목록에는 `processing_status`와 `error_code`가 추가됩니다.
- `POST /api/v1/documents/{id}/retry`: EDITOR/ADMIN, 실패한 색인·삭제 재시도, 202.

기존 HTTP 응답 필드는 유지합니다. 모든 서비스는 공통 형태의 error envelope와
`X-Request-ID`를 사용합니다. 내부 v1 계약은 필드 추가를 허용하고 제거·의미 변경 시
v2를 추가한 뒤 소비자를 순차 배포합니다. 조직/사용자/문서 ID는 서비스 간 값으로만
전달하며 cross-schema FK, JOIN, 공유 트랜잭션은 없습니다.

## 처리와 장애

업로드 파일 최대 25MiB를 문서 행의 임시 bytea와 INDEX 작업에 한 트랜잭션으로 저장합니다.
API와 Worker는 원본 파일 볼륨을 공유하지 않습니다. Worker는 SHA-256을 확인하고 S3·
OpenSearch 처리 후 READY로 바꾸며 임시 bytea를 제거합니다. 장기 저장은 S3가 담당합니다.
큐에는 민감한 원본이 일시적으로 들어가므로 DB·백업의 접근·암호화 정책도 적용해야 합니다.

작업은 SKIP LOCKED, 300초 lease, heartbeat, 문서별 advisory lock, lease token fencing을
사용합니다. 최대 8회 지수 backoff 재시도 후 FAILED로 표시합니다. 결정적 object/chunk ID로
외부 작업을 중복 실행해도 복구할 수 있습니다. 전체 재색인은 새 physical index를 완성하고
publication barrier에서 신규 READY 벡터·삭제 상태를 반영하고 건수를 검증한 뒤 alias를 교체합니다.
서로 다른 문서의 S3·파싱·임베딩은 병렬 수행합니다. 실패하면 기존 alias를 유지합니다. 이전 physical
index는 롤백 가능성을 위해 남으므로 별도 보존 기간 정리 작업이 필요합니다.

Redis는 conversation replica 간 LLM 동시 수와 workspace·사용자별 요청 제한을 공유합니다.
Redis 장애 시 503으로 차단하며 자동으로 로컬 제한으로 전환하지 않습니다. 작업 큐는 Redis가
아닌 knowledge의 PostgreSQL이 소유합니다. RabbitMQ·Kafka는 아직 사용하지 않습니다.

삭제는 먼저 DELETING으로 바꾸므로 Worker가 아직 외부 데이터를 제거하지 못했어도 검색에서
제외됩니다. 검색 시 READY ID를 필터링하고 반환 전 다시 DB 상태를 확인합니다.
RAG는 생성 후 출처 ID를 API로 재검증하고 하나라도 삭제됐으면 답변을 차단합니다.
기존 대화에 저장된 인용은 당시 기록을 보존하는 스냅샷입니다.

현재 모든 인증된 Workspace 구성원은 해당 Workspace의 모든 문서를 읽습니다.
문서별 ACL, 개별 SSO, 서비스 메시/mTLS, 분산 trace backend는 이번 범위에 포함되지 않습니다.
PostgreSQL 서버 하나의 장애는 세 서비스에 공통 영향을 줍니다. 이는 논리적 서비스·권한
분리와 별개이며 물리적 DB 분리나 HA는 운영 요구에 따라 추가합니다.

실행·패치·롤백·이관은 [운영 가이드](../docs/microservices.md)를 참고하세요.
