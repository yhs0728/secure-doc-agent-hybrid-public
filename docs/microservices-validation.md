# 환경 검증 기록 · 2026-10-17

**독립 이미지 build, PostgreSQL·Redis 테스트, 실제 전체 흐름, Redis 장애·복구,
Worker 1개/2개 비교를 완료했습니다.** 전체 흐름 성공은 Windows CPU LLM 경로 기준입니다.
GPU 경로의 WSL 응답 지연·메모리 문제 해결이나 운영 배포 완료를 의미하지 않습니다.

## 최종 결과

| 검증 | 결과 | 범위 |
|---|---|---|
| identity·knowledge·conversation·gateway 이미지 | 모두 build 성공 | 기본 독립 Dockerfile 사용. 임시 캐시 Dockerfile 미사용 |
| PostgreSQL·Redis 포함 테스트 | **45 passed, 69.62초** | 권한·RLS·큐·병렬 준비·재색인 경합·공통 제어·메모리 해제·작업 조회·실패 감지·출처 번호 매핑 |
| 별도 프로세스 HTTP smoke | PASS | 로그인·큐 등록·대화 조회·서비스 장애 격리 |
| 실제 전체 흐름 | **PASS** | Gateway 로그인 → 업로드 → S3·임베딩·OpenSearch READY → 실제 근거 답변 → 대화 저장 → 재색인 후 검색 → 삭제 후 출처 제외 → 근거 없는 경우 human review |
| 업로드→READY | **33.141초** | 보완 후 최종 실행의 작은 합성 문서, 실제 S3·임베딩·OpenSearch 경로 |
| 첫 RAG 응답 | **75.594초** | 보완 후 동일 Qwen3 4B Instruct, Windows CPU, context 2048. 이전 예열 실행은 17.609초였으며 환경 부하에 따라 편차가 큼 |
| 공통 슬롯 HTTP 제어 | PASS | 실제 Redis 슬롯을 선점하면 실제 질문 API가 429 반환 |
| Redis 장애·복구 | PASS | 검증 Redis 중지 시 conversation readiness·질문 API가 503. 재시작 후 readiness 200·공통 슬롯 제어 복구 |
| Worker 병렬 실행 | PASS | DB 작업 실행 구간의 최대 중첩이 1개→2개로 증가 |
| 정적 검사 | PASS | Ruff·format·diff 공백·YAML 구문, CPU 실행 스크립트 구문 확인 |
| RabbitMQ·Kafka | 미도입 | 현재 측정에서 추가 브로커가 필요한 근거 없음 |

## 코드 리뷰 보완 및 재검증

- 재색인은 문서별로 비활성 색인에 기록한 뒤 청크·벡터 참조를 해제합니다. 실제 PostgreSQL을
  사용한 회귀 테스트에서 다음 문서 처리 전에 이전 문서의 메모리 참조가 해제됨을 확인했습니다.
  중간 문서 준비 실패 시 생성 중인 색인을 정리하는 경로도 검증했습니다.
- 재색인 요청에 `job_id`를 반환하고, 관리자에게 같은 workspace의 작업 상태 조회를 제공합니다.
  비인증·권한 부족·다른 workspace 접근 차단과 최종 실패 상태 노출을 테스트했습니다.
- 전체 검증은 요청한 작업의 `DONE`, 이전과 다른 색인 세대, 실제 활성 세대 일치를 확인합니다.
  실패·세대 미변경·다른 세대 활성·세대 누락·시간 초과를 성공으로 판정하지 않습니다.
- 첫 실제 검증에서 모델이 합성 문서의 파일명을 잘못 복사해 출처가 제외됐습니다. 답변 내용과
  groundedness 판정은 정상임을 모델 단계별 출력으로 확인했습니다. 모델은 문서 번호를 선택하고
  서버가 원래 파일명으로 매핑하도록 수정한 뒤 전체 흐름이 통과했습니다.
- 보완 후 보고서: `.microservice-tests/full-stack-review-fixed.json`, run `f2077875e901`,
  `passed=true`, 9개 검사 통과. 재색인 작업 `1f66a20c-ede0-48e4-8c0f-f7aa78dd5869`는
  `DONE`이며 `generation_before`와 `generation_after`가 다름을 확인했습니다.
- 최종 회귀 테스트 **45 passed, 69.62초**, 별도 프로세스 HTTP smoke PASS, Knowledge·Conversation
  독립 이미지 build PASS, Ruff·format·diff 검사 및 YAML 9개·Compose·실행 스크립트 구문 PASS.

## Worker 성능 비교

아래 Worker 1개/2개 비교는 리뷰 보완 이전에 측정한 기록입니다. 보완 후 전체 흐름 검증은
새 실행 `f2077875e901`에서 통과했으며, 병렬 처리량 비교를 다시 측정한 결과는 아닙니다.

동일 호스트·모델·workspace에서 문서 6개, 문서당 합성 문단 200개로 비교했습니다.
예열은 측정에서 제외했고 각 실행의 삭제 큐까지 비운 뒤 다음 실행을 시작했습니다.
LLM 모델은 측정 전에 메모리에서 내렸으며 기존 레거시 서비스는 계속 가동했습니다.

| 지표 | Worker 1개 | Worker 2개 |
|---|---:|---:|
| 전체 READY 완료 시간 | 18.063초 | 11.562초 |
| 처리량 | 0.3322문서/초 | 0.5189문서/초 |
| READY 중앙값 | 11.750초 | 8.148초 |
| 평균 준비 시간 | 2,421.193ms | 2,980.607ms |
| 평균 게시 시간 | 175.615ms | 159.800ms |
| 평균 게시 lock 대기 | 1.651ms | 1.717ms |
| DB 작업 실행 구간 최대 중첩 | 1 | 2 |
| 완료 INDEX 작업 | 6 | 6 |
| 삭제 요청 실패 | 0 | 0 |

이번 측정에서는 전체 시간이 약 **36% 감소**, 처리량은 약 **1.56배**였습니다.
작업별 준비 시간은 자원 경합으로 증가했지만 두 작업의 실행이 겹쳐 전체 완료 시간이 줄었습니다.
단일 호스트의 작은 배치 1회씩 비교한 결과이며, 운영 부하·대형 문서·장애 부하 테스트나
일반적인 성능 개선 배수를 보장하지 않습니다.

준비 시간이 게시·lock 대기보다 큰 비중을 차지했습니다. 현재는 PostgreSQL 내구성 큐를
유지하고 Worker 수·메모리·CPU·임베딩 비용을 관찰합니다. polling/DB 경합, fan-out, 전용 DLQ가
필요해질 때 outbox·confirm·manual ACK·멱등성을 포함해 RabbitMQ를 검토합니다.

## 실환경에서 발견하고 수정한 사항

- 이전 root 실행으로 Redis AOF 하위 파일이 root 소유로 남아 비관리자 실행이 실패했습니다.
  검증용 Redis 볼륨의 소유권을 일회성 이전해 복구했고 데이터는 초기화하지 않았습니다.
- Knowledge API의 첫 검색이 모델 초기화 때문에 약 116.7초 걸려 의존성 timeout을 초과했습니다.
  모델 로딩을 API 기동 단계로 옮기고 기동 유예를 10분으로 늘렸습니다. 모델이 준비되지 않으면
  API가 요청을 받지 않도록 테스트했습니다. adapter 대역을 쓰는 test 환경은 사전 로딩을 생략합니다.
- native HTTP smoke는 클라이언트를 재사용하고 timeout을 30초로 명시해 기동 부하 중의
  검증 클라이언트 시간 초과를 줄였습니다. 서비스 자체의 의존성 timeout은 늘리지 않았습니다.
- 이전 실패 실행의 다른 문서가 같은 답을 뒷받침하면 삭제 후에도 답변이 가능한 것이 정상입니다.
  검증기는 항상 삭제 문서의 출처 제외를 확인하고, READY 문서가 전혀 없을 때만 human review를
  요구하도록 수정했습니다. 최종 실행에서는 남은 READY 문서가 없어 두 조건 모두 확인했습니다.
- 문서 합성 내용에 실행 ID를 넣어 반복 벤치마크의 checksum 중복을 방지하고, 보고서에
  실패 유형·삭제 요청 실패 수를 남기도록 했습니다.

## 실행 환경과 복구

C: 공간 부족으로 중단됐던 환경에서 공간을 확보한 뒤 검증을 재개했습니다. WSL 응답이
`WSAETIMEDOUT`으로 멈춰 사용자 승인 후 Ubuntu를 재시작했습니다. 기존 컨테이너를 다시
기동했고 기존 업무 DB·문서·검색 볼륨을 삭제하거나 자동 이관하지 않았습니다.

WSL은 약 7.7GiB, Windows는 약 15.8GiB 메모리 환경입니다. 같은 WSL 안의 CPU LLM도
기존 서비스와 메모리가 경합해 최종 검증에는 Windows의 별도 CPU Ollama를 사용했습니다.
기존 11434 서버는 교체하지 않았습니다. 검증 서버는 Windows WSL 가상 어댑터의 11435 포트,
동일한 `qwen3:4b-instruct` 모델, context 2048, `size_vram=0`으로 확인했습니다.

최종 검증 Compose 파일은 `compose.yaml` + `compose.validation.yaml` +
`compose.validation.offline.yaml` + `compose.validation.cpu.yaml`입니다. offline 설정은 해당
검증 프로젝트에 다운로드한 모델 캐시를 사용하며 레거시 모델 볼륨을 참조하지 않습니다.
`VALIDATION_CPU_LLM_URL`은 Git 제외 `.env.microservices`에만 지정했습니다.

임시 네이티브 테스트 DB는 종료했습니다. 벤치마크 합성 문서의 삭제 요청은 전부 성공했고
PENDING/RUNNING 큐가 0인 것을 확인했습니다. 초기 중단 때의 FAILED 작업 이력은 성능 집계에서
실행 ID로 제외했습니다. 업무 데이터의 실제 이관·트래픽 전환, Kubernetes 배포, 원격 CI 실행,
Redis HA 검증은 이번 작업에서 실행하지 않았습니다.

## 결과 파일과 재실행

아래는 로컬 실행 산출물이며 Git에서 제외됩니다.

- `.microservice-tests/full-stack.json`: 최종 전체 흐름 `passed=true`
- `.microservice-tests/control-plane.json`: 실제 HTTP 공통 제어·Redis 장애·복구 `passed=true`
- `.microservice-tests/workers-1.json`, `workers-2.json`: 개별 실측
- `.microservice-tests/worker-comparison.json`: 실행 ID별 DB timing·중첩 집계
- `full-stack-resumed.json`, `full-stack-stable.json`, `full-stack-cpu*.json`: 중간 실패 이력

명령과 CPU 서버 기동 방법은 [운영 가이드](microservices.md)를 참고하세요.
테스트는 별도 폐기용 `_test` DB의 `MICROSERVICES_TEST_DSN`과 실제 Redis의
`MICROSERVICES_TEST_REDIS_PASSWORD`·`MICROSERVICES_TEST_REDIS_PORT`를 설정한 뒤 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m pytest microservices/tests -q
```

이전 분리 시점의 backend 166 passed·frontend 단위 2 passed·Playwright 7 passed는 이전
코드에 대한 기록입니다. 이번 결과로 대체하거나 실제 LLM 검증 결과와 합산하지 않았습니다.
