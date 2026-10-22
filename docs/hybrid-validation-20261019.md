# 하이브리드 구현·검증 기록 — 2026년 10월 19일

## 결과

| 검증 | 결과 | 실제 범위 |
|---|---|---|
| 백엔드 회귀 | 108 passed, 0 skipped | 새 Docker PostgreSQL·Redis, 실제 DB 권한·migration·HTTP 라우트·큐·admission. 외부 검색·객체 저장소·LLM은 대역 |
| 외부 추론 정책·장애 주입 | PASS | 기본 차단, 정확한 UUID 허용, 단계별 재검사, 연결·시간 초과·429·서버 실패, 프로세스별 호출 차단·복구 |
| 사용자·문서 접근 | PASS | 인증된 context 사용, 클라이언트 허용 우회 차단, 삭제 문서 재확인, 슬롯 반환 |
| 응답·대화 보존 | PASS | 검색 전환 모드·사유·발췌·출처 저장 및 대화 조회 |
| AWS 키 없는 Conversation 기동 | PASS | 외부 전송 전면 차단 시 키 불필요. 허용 작업공간+키 누락은 기동 오류. DB·Redis·검색 등 로컬 인프라는 별도 필요 |
| 프런트엔드 | PASS | TypeScript·Vite 프로덕션 빌드, Vitest 2개 |
| Chromium 브라우저 | 7 passed | Mock HTTP API 기반 로그인·채팅·저장된 대화·검색 전환 UI. 실제 AWS 연결 E2E 아님 |
| Conversation Docker 이미지 | PASS | Python 3.12 이미지 실제 빌드 |
| 이미지 보관·복원 | PASS | 실제 이미지 save·SHA-256·load 후 `--pull never`로 애플리케이션 import. 서비스 교체·DB 롤백 아님 |
| 정적 검사 | PASS | 변경된 Python의 Ruff, Compose config, variant 검사, git diff 공백 검사 |
| 실제 배포 전체 흐름 | PASS | 실제 PostgreSQL·Redis·객체 저장소·임베딩·OpenSearch·Bedrock. 9개 확인 항목 통과 |
| 실제 AWS 호출 | PASS | 도쿄 `qwen.qwen3-32b`, 합성 문서 기반 실제 RAG 그래프. 검색기는 fixture. 이번 1회 2.234초 |

백엔드 최종 실행: 108개, 14.38초. 환경·범위가 제한된 회귀 검증이며 처리량·응답 SLA·동시 사용자 수나 운영 가용성을 뜻하지 않는다.

이미지 ID: `sha256:f86a27958ae565fc07e48c2fa50671481e4ecc80a4ee588daab702bf08c86b5c`

아카이브 SHA-256: `6d9e32fd4a2a5de38a80d8c77d9a029084da664f995bf4c3a4a1308a78a0f481`

## 코드·환경 범위

이번 변경은 `hybrid` 저장소에 적용했다. `local`·`multicloud` 애플리케이션 소스는 수정하지 않았다. Python 실행은 기존 로컬 가상환경을 재사용했고 프런트엔드 의존성은 hybrid 안에 설치했다. 기존 코드 리뷰의 미커밋 변경을 보존했다. 테스트 DB·Redis 컨테이너는 격리 생성했고 해당 테스트 컨테이너만 종료·제거했다. 실제 운영 스택은 교체하지 않았다.

증빙 원본은 Git 제외 경로 `.microservice-tests/hybrid-pytest.xml`, `hybrid-pytest.txt`, `release-cache.json`에 있다. 오프라인 이미지와 override는 `.releases/conversation-20261019-final`에 보관했다. 이 문서와 저장된 원본 실행 결과를 함께 해석한다.

## 실제 AWS 연결 단계

`.env.bedrock`의 `BEDROCK_API_KEY`, 리전·모델을 설정한 후 `python tools/verify_bedrock_connection.py`를 실행한다. 합성 문서만 실제 Bedrock으로 전송하며 입력·출력 본문과 키는 결과 파일에 기록하지 않는다. 호출은 토큰 요금이 발생할 수 있고 새 AWS 인프라는 생성하지 않는다.

검증 도구는 실제 RAG 그래프의 재작성·관련성·생성·근거 판단 경로와 제공자 연결을 사용한다. 검색기는 합성 fixture이며 운영 DB·스토리지 전체 E2E가 아니다. 통과하면 `.microservice-tests/bedrock-live.json`의 실제 값과 범위를 이 문서에 추가한다. 실제 AWS 호출이 통과했다. 이 단계는 합성 검색기와 실제 Bedrock을 결합한 검증이며, 배포된 전체 스택의 검증 결과는 아래 별도 기록으로 구분한다.

## 운영 목표와의 차이

VPN·PrivateLink·다중 AZ·DB 자동 failover·CloudWatch 수집·이미지 서명 검증·문서별 등급 정책·부하 테스트는 아직 완료하지 않았다. 로컬 모델 자동 failover도 구현하지 않았으며 검색 발췌로 기능을 축소한다. 차단기는 replica 공통 상태가 아니다. 가용성·보안·비용 개선 수치를 만들지 않는다.

자소서에는 [검증 범위에 맞춘 문안](cover-letter-hybrid.md)을 사용한다.


## 실제 Bedrock 호출 확인

2026년 10월 19일 사용자가 설정한 키로 실제 호출을 실행했다. 합성 정책 문서의 비밀번호 변경 주기를 질의하고, 원래 RAG 그래프의 답변·출처 선택·근거 판단이 통과함을 확인했다. 키와 문서·생성 본문은 결과 파일에 보관하지 않았다. 일반 작업공간의 외부 전송 허용 목록은 변경하지 않았다.

이번 한 번의 실행은 2.234초였다. 단일 작은 합성 문서 실행으로 운영 지연·동시성·품질 개선 배수를 주장하지 않는다. 실제 저장소·임베딩·검색과 결합한 전체 서비스 검증은 별도 결과 파일로 기록한다.


## 실제 배포 전체 흐름 검증

도쿄 Bedrock Qwen3-32B와 별도 Docker 검증 프로젝트를 연결했다. 합성 문서만 사용했고 다음 9개 항목이 모두 통과했다.

1. 실제 Gateway 응답.
2. 관리자 로그인.
3. 실제 객체 저장소·임베딩·검색 색인을 거쳐 문서 READY.
4. 실제 Bedrock의 답변과 출처·근거 판단.
5. 대화 이력의 DB 보존.
6. 재색인 작업 DONE 및 다른 색인 세대로 전환.
7. 재색인 이후 검색·답변.
8. 지식이 비었을 때 검토 필요 응답.
9. 삭제 문서를 이후 답변 출처에서 제외.

실행 ID: `eb61c8c78233`. 업로드에서 READY까지 28.391초, 첫 RAG 응답 4.781초였다. 초기 준비 상태와 작은 합성 문서 1건을 포함한 결과이며 SLA·부하 성능이나 평균 응답시간으로 일반화하지 않는다.

결과 파일: `.microservice-tests/bedrock-full-stack.json`. 직접 확인할 합성 데모는 `.microservice-tests/bedrock-demo.json`에 별도 기록했다. 테스트용 작업공간만 외부 추론을 허용했고 일반 `.env.bedrock`의 허용 목록을 확대하지 않았다.

### 직접 확인

- UI: http://127.0.0.1:18182
- 계정: `.env.microservices`의 `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD`. 이 문서에 비밀번호를 복사하지 않는다.
- 데모 문서: `SYNTHETIC-ONLY-aws-hybrid-demo.txt`.
- 예시 질문: “합성 데모의 가상 테스트 계정은 비밀번호를 며칠마다 변경하나요?”
- 재현: `python tools/verify_bedrock_stack.py --no-build`. 이미지가 없으면 `--no-build`를 생략한다. 실제 AWS 호출 요금이 발생할 수 있다.

이 검증 UI의 허용 작업공간에는 합성·공개 테스트 문서만 올린다. 실제 업무 문서는 별도 전송 정책과 작업공간을 사용한다.

실행 중인 프로젝트: `secure-doc-agent-hybrid-cloudcheck-20261019`. 프로젝트 상태는 `docker ps --filter label=com.docker.compose.project=secure-doc-agent-hybrid-cloudcheck-20261019`로 확인한다. 종료할 때는 해당 프로젝트만 지정하고, 데이터 볼륨을 지우는 옵션은 추가하지 않는다.


## AWS 운영·FinOps 추가 검증

도쿄 CloudFormation 13개 자원 배포, 기본 설정 16개·추가 설정 7개 확인, 실제 ECR conversation 게시·OCI digest 일치·S3 SHA-256 검증·CloudWatch 집계 전송 재조회·로컬 Grafana/Prometheus 7개 검사를 완료했다. 전체 서비스 테스트 119개와 OCI 게시 형식 회귀 테스트 3개가 통과했다. FinOps 활성화 상태의 최신 실제 E2E는 8개 검사 통과이며 단일 합성 실행 RAG 3.187초는 성능 보장 지표가 아니다.

[공개 검증 증거](evidence/aws-hybrid-finops-validation-20261019.json), [FinOps 운영법과 예산·잔여 위험](hybrid-finops.md)을 함께 참고한다. 이미지 OS 스캔에서 High 3건이 남아 운영 승격 검사는 실패 상태로 보관했다. 배포 자원·기능 테스트 성공과 이미지 보안 승인 성공을 구분한다.
