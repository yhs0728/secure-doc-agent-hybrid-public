# 저장소 분리 검증 · 2026-10-17

프로필: `hybrid`. 원본 기준 커밋: `902ff42`.

| 검증 | 결과 |
|---|---|
| PostgreSQL·Redis 포함 회귀 테스트 | 55 passed, 21.09s |
| 저장소 프로필 검사 | PASS |
| Docker Compose 구성 검사 | PASS, 클라우드에는 더미 API key 사용 |
| Kubernetes 프로필 | N/A |
| 클라우드 실서비스 검증 | 미실행 |

기준 로컬 구현의 전체 Git 이력을 보존하고 독립 원격 저장소로 분리했습니다.
`baseline-local-2026-10-17` 태그는 원본 로컬 커밋, `v0.1.0`은 해당 저장소의 첫 배포 프로필을 가리킵니다.

원본 로컬 CPU LLM의 실제 E2E 기록은 `docs/microservices-validation.md`에 있습니다.
이번 회귀 테스트의 S3·OpenSearch·모델 어댑터는 결정적 테스트 대역이며 PostgreSQL·Redis는 실제 서버를 사용했습니다.
Bedrock 연결 테스트는 요청 설정·HTTPS endpoint 검증·응답 토큰 한도 전달을 검사하며 실제 AWS 계정 호출을 수행하지 않습니다.

새로운 AWS/GCP 리소스를 생성하지 않았고 실제 자격 증명·기존 런타임 데이터는 복사하지 않았습니다.
클라우드 버전의 실제 E2E에는 사용자 계정의 리전·모델 접근 권한·인증 정보·배포 환경 준비가 필요합니다.

## 하위 작업 폴더 재배치 검증 · 2026-10-18

- 위치: `C:\llm-study\secure-doc-agent\hybrid`. 원격 저장소와 전체 Git 이력 유지.
- PostgreSQL·Redis 연동 포함 마이크로서비스 회귀 테스트: **59 passed**, skip 없음.
- 프런트엔드 TypeScript 검사와 프로덕션 빌드: PASS. 기존 설치 의존성을 임시 연결해 검사 후 연결 제거.
- 일반/검증 Compose 6개 구성: PASS. 선택적 모니터링 포함 호스트 포트 45개 중복 없음.
- 프로젝트명과 볼륨 이름 고정, 버전별 애플리케이션 이미지 이름 분리 검사: PASS.
- 현재 디렉터리 변경 및 추가 Compose override 파일의 절대 경로 처리: PASS.
- OCI + AWS Kubernetes 오프라인 렌더링: 16개 리소스, Deployment 5개의 OCIR pull secret 확인.

새 프로필의 컨테이너나 유료 클라우드 리소스를 생성하지 않았습니다. 기존 상위 서비스는 재시작하지 않았으며,
Bedrock·OCI 실계정 연결과 새 프로필 전체 HTTP E2E는 이번 경로 변경 검증에 포함하지 않았습니다.

## 최상위 폴더 정리 · 2026-10-18

- 일반 파일 트리 최상위는 `local`, `hybrid`, `multicloud` 세 폴더입니다.
- 원본·기존 환경 설정·Git 이력 보관본: `local/.archive/original-workspace` (Git 제외).
- 개발 Python 환경: `local/.venv`, 부하 테스트 환경: `local/.venv-load`. 활성화 스크립트와 실행기 갱신 완료.
- VS Code 작업 공간: `local/secure-doc-agent.code-workspace`.
- 경로 관련 테스트: 이 저장소 4개 통과, 세 저장소 합계 19개 통과.
- 로컬 프런트 TypeScript 검사·프로덕션 빌드 통과.
- 기존 실행 컨테이너 19개 정상, 영속 볼륨·포트 유지 및 Redis·모니터링 bind 경로 갱신 확인.
- 기존 검증 스택(18080)의 실제 전체 HTTP 흐름 통과: 로그인·업로드·임베딩·검색·실제 CPU LLM 답변·대화 저장·재색인 DONE/세대 교체·삭제 반영.
- 검증 보고서는 `local/.microservice-tests/layout-full-stack.json`에 보존합니다.

위 전체 흐름 결과는 기존 검증 스택에 대한 결과이며 새 세 프로필의 실계정 클라우드 배포 결과가 아닙니다.
최상위 숨김 `.git`은 세션의 관리 권한상 읽기 전용으로 보호되어 이동되지 않았습니다. ACL 변경이나 삭제는 하지 않았고 이력은 보관 위치에 복사했습니다.
