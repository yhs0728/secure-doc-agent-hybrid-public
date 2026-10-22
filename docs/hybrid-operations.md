# 하이브리드 실행·장애·패치 운영

## 실행

```powershell
python tools/prepare_microservices_env.py
Copy-Item .env.bedrock.example .env.bedrock  # 아직 파일이 없을 때만
python tools/compose.py config --quiet
python tools/compose.py up -d --build
```

이미 존재하는 환경 파일을 덮어쓰지 않는다. 기본 `HYBRID_EXTERNAL_WORKSPACES=`는 외부 추론 전면 차단이다. 이 경우 Bedrock 키가 없어도 검색 전용으로 기동할 수 있다. 외부 호출을 허용하려면 `.env.bedrock`에 키·리전·모델을 설정하고, 외부 처리 가능한 문서만 담은 전용 작업공간 UUID를 목록에 넣은 뒤 Conversation을 다시 생성한다. 정확한 UUID만 허용하며 `*`는 기동 시 거부한다. 환경 파일은 Git에서 제외된다.

이 정책은 **작업공간 단위**다. 문서별 기밀 등급 판별·마스킹·조직 승인 워크플로를 구현한 것은 아니다. 민감 문서와 외부 전송 가능 문서를 한 허용 작업공간에 섞지 않는다. Ollama 모드는 운영자가 로컬 모델로 지정한 경로이며 임의 외부 Ollama 서버가 안전한 것으로 자동 판정되는 것은 아니다. 네트워크 송신 정책은 별도로 적용한다.

## 장애 동작

| 상황 | 동작 |
|---|---|
| 외부 추론 비허용 작업공간 | 클라우드 모델 생성·재작성·판정 호출 없이 로컬 검색 발췌 |
| 연결 실패·시간 초과·429·5xx | 검색 발췌로 전환, `requires_human_review=true` |
| 제공자 400·401·403·404 등 설정 오류 | `PROVIDER_CONFIGURATION_ERROR` 503. 장애 성공 응답으로 숨기지 않음 |
| 연속 외부 추론 실패 | 프로세스별 circuit open. 기본 30초 이후 시험 요청 1개 |
| Redis·인증·검색 장애 | 기존 fail-closed 정책 유지. 검색 전환으로 권한·용량 통제를 우회하지 않음 |
| 삭제·권한이 변경된 문서 | 검색 후 문서 유효성을 재확인하고 제외 |

검색 발췌는 질문에 대한 정답·관련성·근거 충족을 보장하지 않는다. 최대 3개 문단, 문단당 최대 500자를 제공하고 원문 확인을 안내한다. 검색 품질이 나빠도 외부 모델로 검색어를 다시 쓰지 않는다. 응답 모드·사유는 DB와 대화 조회 API에 보존된다.

외부 HTTP 호출 제한은 기본 30초, 새 모델 호출을 시작할 수 있는 워크플로 예산은 90초다. 이 예산은 진행 중인 HTTP 요청을 강제 취소하는 전체 요청 deadline이 아니다. 그래프 단계가 시작되기 전 예산을 확인하므로 전체 소요 시간에는 마지막 호출과 로컬 검색·DB 시간이 추가될 수 있다. 기본 제공자 재시도는 0회이며, 오류를 다른 외부 모델로 자동 전송하지 않는다.

차단기는 각 프로세스의 메모리 상태다. replica 전체가 공유하는 차단기로 주장하지 않는다. 기존 Redis는 replica 공통 admission·rate limit을 유지한다. 프로세스 재시작 시 circuit은 초기화된다. 모델 API 가용성과 프로세스 readiness는 구분한다.

## 관측

기존 `/metrics`에 `secure_doc_hybrid_responses_total{mode,reason}`와 `secure_doc_hybrid_circuit_open`을 추가했다. 질문·문서·사용자 ID를 새 지표 라벨로 넣지 않는다. Prometheus 경보는 실제 장애 전환과 정책에 따른 검색 전용 응답을 구분한다. 이 변경은 로컬 지표·경보 구성까지이며 CloudWatch 업로드나 로그 디스크 버퍼는 구현하지 않았다.

## 이미지 보관·검사·복원

```powershell
python tools/release_cache.py package .releases/release-20261019 --image conversation=secure-doc-agent-hybrid/conversation:hybrid-20261019
python tools/release_cache.py verify .releases/release-20261019
python tools/release_cache.py restore .releases/release-20261019
python tools/release_cache.py restore .releases/release-20261019 --apply
```

`restore` 기본 동작은 검증·계획 출력이다. `--apply`는 검증한 이미지를 Docker에 적재하고 `compose.images.json`을 만들며 서비스를 배포하지 않는다. 새 디렉터리에만 패키징하여 기존 릴리스를 덮어쓰지 않는다. Knowledge API와 Worker는 같은 이미지로 함께 지정해야 한다. DB·스토리지·Redis 등의 상태 서비스는 대상에 넣을 수 없다.

운영 설정을 유지한 개별 교체 예:

```powershell
python tools/compose.py -f .releases/release-20261019/compose.images.json up -d --no-deps --no-build --pull never conversation
```

이 명령은 실제 서비스 변경이므로 변경 전 릴리스·백업·의존성·준비 상태를 확인한 뒤 실행한다. 이번 검증에서는 운영 서비스 교체를 실행하지 않았다. SHA-256은 파일 손상 검출이며 배포자 신원 확인이 아니다. 아카이브·manifest를 신뢰할 수 있는 채널로 전달하고 운영 공급망에는 별도 서명 검증을 연결해야 한다.

추가 DB migration은 `messages.response_mode`, `messages.response_reason` 컬럼이다. 이전 이미지의 INSERT·SELECT를 유지할 수 있도록 기본값을 가진 컬럼 추가로 구성했다. 이미지 복원은 데이터 복구가 아니며 스키마·모델·색인 호환성을 함께 검토한다.

## 실제 AWS 호출

```powershell
python tools/verify_bedrock_connection.py
```

무작위 합성 작업공간과 합성 정책 문서만 사용해 실제 RAG 그래프의 모델 단계들을 Bedrock으로 호출한다. 키·출력 본문·제공자 응답 오류를 출력하지 않고 리전·모델·성공 여부·시간만 `.microservice-tests/bedrock-live.json`에 기록한다. 실제 토큰 요금이 발생하며 새 AWS 인프라는 만들지 않는다. 검색기는 합성 fixture이므로 실제 배포된 DB·저장소까지의 E2E와 구분한다. 업무 작업공간의 허용 목록은 변경하지 않는다.

실제 전체 스택 검증은 `.env.microservices`와 `.env.bedrock`의 전용 검증 환경을 준비한 뒤 기존 `tools/verify_full_stack.py`를 사용한다. 샘플 문서만 사용하고 외부 전송이 가능한 전용 작업공간임을 먼저 확인한다.
