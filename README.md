# SecureDoc Agent — 로컬 + AWS

로컬 업무 서비스와 AWS Bedrock 추론을 연결하는 하이브리드 구현입니다.

검토한 현재 코드와 기술 문서를 담은 공개용 스냅샷입니다. 원본 개발 커밋과 GitHub Actions 실행 이력은 포함하지 않습니다. 이 저장소의 GitHub Actions 자동 실행은 비활성화되어 있습니다.

| 버전 | 공개 저장소 |
|---|---|
| 기본 Agent | [secure-doc-agent-public](https://github.com/yhs0728/secure-doc-agent-public) |
| 하이브리드 | [secure-doc-agent-hybrid-public](https://github.com/yhs0728/secure-doc-agent-hybrid-public) |

실행은 [버전별 가이드](DEPLOYMENT.md), 서비스 경계는 [운영 문서](docs/microservices.md),
기존 프로젝트 설명은 [원본 README](README.original.md)를 참고하세요.

기준 로컬 버전은 PostgreSQL·Redis 테스트 45개와 실제 CPU LLM 전체 흐름을 통과했습니다.
이 기록은 클라우드 배포 검증을 의미하지 않습니다. 새 저장소에는 런타임 데이터·실제 환경 파일·
비밀 키를 복사하지 않습니다. 저장소를 만드는 작업은 유료 클라우드 자원을 생성하지 않습니다.

버전 공통 수정은 `git cherry-pick <commit>`으로 필요한 저장소에 명시적으로 반영합니다.
각 저장소의 배포 설정과 버전 태그는 독립적으로 관리하며 자동 동기화하지 않습니다.

Docker 실행은 `python tools/compose.py`를 사용하며 프로젝트명 `secure-doc-agent-hybrid`가 고정됩니다.
다른 버전과 포트·애플리케이션 이미지·볼륨을 공유하지 않습니다.

## 코드 리뷰 수정

테스트 DB 안전장치, 오류 관측·경보 복구, 파서·대화 이력 제한과 Compose 옵션 전달을 보완했습니다. [변경 내용과 검증 결과](docs/code-review-fixes.md)를 참고하세요.


## 하이브리드 장애 격리·전송 정책

외부 추론은 기본 차단이며 허용된 작업공간만 호출합니다. 키가 없어도 검색 전용으로 기동할 수 있습니다. 장애 시 문서 발췌 전환과 대화 이력 표시, 프로세스별 호출 차단, 로컬 이미지 보관·복원을 추가했습니다. [운영 절차](docs/hybrid-operations.md), [검증 기록](docs/hybrid-validation-20261019.md)을 참고하세요.


## AWS 배포와 FinOps

도쿄 ECR·S3·CloudWatch·Budgets 실제 배포, 앱 공유 호출 한도와 Grafana, 검증 방법은 [운영 및 FinOps 안내](docs/hybrid-finops.md)를 참고하세요.


최종 보완 및 Git 게시 전 검증: [143개 백엔드·8개 UI·실제 AWS 검사 결과](docs/hybrid-final-validation-20261019.md).
