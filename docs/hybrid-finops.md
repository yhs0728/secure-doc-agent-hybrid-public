# SecureDoc Hybrid 운영과 FinOps

대상: `hybrid` 전용, Tokyo `ap-northeast-1`. 월 30 USD는 초기 포트폴리오 운영 목표이며 AWS의 지출 보장 상한이 아니다. 로컬 전기·장비 비용, 환율과 기존 계정 자원 비용은 별도 고려한다.

## 현재와 배포할 구성

| 구성 | 역할 | 적용 범위 |
|---|---|---|
| 로컬 PostgreSQL·Redis·OpenSearch·객체 저장소 | 인증, 문서, 임베딩, 검색, 이력, 공동 호출 제어 | 기존 실행 중 |
| Bedrock Qwen3-32B | 답변·근거 검증, 도쿄 API 호출 | 실제 호출 검증 완료 |
| ECR 4개 저장소 | 서비스별 이미지, immutable 태그, 기본 push 스캔 | 계정 배포 및 설정 조회 검증 완료 |
| S3 배포 버킷 | 이미지 아카이브·manifest·검증 보고서 | 비공개, TLS 강제, SSE-S3, 버전 관리 |
| CloudWatch | Mantle 호출·토큰 대시보드, 콘솔 경보 3개, 운영 로그 14일 | 계정 배포 및 실제 집계 전송·조회 완료 |
| AWS Budgets | 계정 월 30 USD·Bedrock 월 20 USD, 지정 이메일 | 실제 50/80/100%, 예상 100% 알림 |
| 앱 FinOps | 모든 LLM 단계에서 Redis 원자적 예약·한도 | Bedrock Compose에서 기본 켜짐 |

CloudFormation은 IAM 사용자·액세스 키·인바운드 포트를 만들지 않는다. 운영 자격 증명을 앱 컨테이너에 주입하지 않는다. 프로비저닝은 AWS CLI의 임시 개발 프로파일로 실행한다. 워크로드 장기 운영용 IAM Roles Anywhere는 인증서 발급·신뢰 정책 설계 후 별도로 적용한다.

## 예산의 근거와 제한

- 추론 20 USD, 레지스트리·파일·관측 데이터 5 USD, 여유 5 USD를 초기 배분한다. 실제 요금 견적이 아니라 운영 목표다.
- 모델 단계 호출은 UTC 일 60회·월 600회, 질문당 8회까지다. 질문 하나가 여러 호출을 사용하므로 질문 수와 다르다.
- 입력은 호출당 직렬화 UTF-8 32,000바이트, 출력은 최대 1,024토큰. 큰 입력은 조용히 잘라 답변하지 않고 검색 결과로 전환한다.
- 호출 전에 입력 바이트 + 1,024의 여유량과 출력 상한을 내부 통제 단가에 대입해 예약한다. 내부 단가는 입력 1 USD/백만, 출력 5 USD/백만이다. 이는 **AWS 실제 단가가 아니며 토크나이저 기반의 정확한 청구 예측도 아니다**.
- 예약 합계 일 1 USD·월 20 USD 한도와 호출 수 한도 중 먼저 도달하는 것을 적용한다. 실패·타임아웃·사용량 미반환도 예약을 환불하지 않는다. 실제 토큰 수는 응답 usage metadata에서 별도 누적한다.
- 초과 시 `search_only` / `finops_budget`, 검토 필요 표시. Redis 제어 불가 시 새 외부 호출을 허용하지 않는다. 기존 공유 입장 제어가 Redis 장애에서 HTTP 503을 반환할 수 있다.
- Redis AOF everysec·noeviction을 사용한다. 데이터 삭제·복구 손실·별도 Redis·직접 AWS 호출에는 앱 제한이 적용되지 않는다. AWS 계정 전체의 확정 달러 상한으로 주장하면 안 된다.
- AWS Budgets는 보통 8~12시간 간격으로 갱신되며 추가 청구 지연이 있다. 알림만으로 실시간 차단되지 않는다.

공식 AWS Price List Query API에서 Tokyo·Qwen3-32B·Mantle·Standard 단가를 확인했다. 입력 **백만 토큰당 0.18 USD**, 출력 **백만 토큰당 0.73 USD**다. 원본 단위 `1K tokens`를 백만 단위로 변환했다. [공개 가격 조회 증거](evidence/bedrock-qwen3-32b-tokyo-pricing-20261019.json)를 보관했다. 모델·리전·서비스 등급 변경, 세금·할인·다른 서비스 요금은 따로 반영해야 한다.

이번 앱 검증의 입력 4,473·출력 106토큰은 이 단가로 약 **0.000883 USD의 추론 사용량**에 해당한다. 실제 청구서 금액이 아니라 토큰 기반 추정이며, 내부 예약액 약 0.039846 USD와 구분한다. 질문별 모든 모델 단계의 합계로 계산해야 한다. 성능이 좋은 모델로 교체할 때에도 모델별 단가와 같은 평가셋 결과부터 확인한다.

## 인증 및 배포

AWS CLI 2.32.0 이상을 설치하고 PowerShell에서 실행한다.

```powershell
aws login --profile secure-doc-hybrid --region ap-northeast-1
aws sts get-caller-identity --profile secure-doc-hybrid
```

IAM 사용자는 `SignInLocalDevelopmentAccess`가 필요할 수 있다. 이 정책은 CLI 로그인용이며 ECR·S3·CloudWatch·Budgets 배포 권한을 자동 부여하지 않는다. 계정 관리자가 개발 신원에 이 스택의 자원 생성·조회 권한을 부여해야 한다. Root로 배포하지 않는다. 회사 Identity Center가 있다면 `aws configure sso --profile secure-doc-hybrid`를 사용한다. SSO 디렉터리 리전은 서비스 Tokyo 리전과 다를 수 있다.

로컬의 무시되는 `.env.finops`에 프로파일·이메일·예산이 준비되어 있다. 키를 입력하는 파일이 아니다. 저장소 루트에서:

```powershell
.\local\.venv\Scripts\python.exe hybrid/tools/aws_finops.py plan
.\local\.venv\Scripts\python.exe hybrid/tools/aws_finops.py auth
.\local\.venv\Scripts\python.exe hybrid/tools/aws_finops.py deploy --apply
.\local\.venv\Scripts\python.exe hybrid/tools/aws_finops.py verify
```

`deploy --apply`는 위 표의 소규모 자원을 실제로 생성한다. EC2/GPU/EKS/RDS/관리형 OpenSearch/NAT Gateway/VPN/PrivateLink를 생성하지 않는다. 서비스가 늘어날수록 좋다는 기준 대신 추론 품질과 배포 복구·비용 통제의 증거를 우선한다. 네트워크 전용선과 사설 엔드포인트는 고정 비용 및 Mantle 지원 경로를 확인한 별도 설계가 필요하다. 현재 경로는 AWS HTTPS 공개 API에 대한 아웃바운드 연결이다.

스택 삭제 시 S3 버킷과 ECR 저장소는 `Retain`되어 **비용도 남을 수 있다**. 릴리스·태그 이미지는 자동 만료시키지 않는다. ECR untagged만 14일 뒤 정리하고 S3 `reports/`만 30일 보관한다. 이전 릴리스 정리는 복구 범위를 검토하고 수동 진행한다. 이미지 총 5GB, 아카이브 총 5GB를 운영 점검 기준으로 두며 이는 저장소의 하드 쿼터가 아니다.

## 사용자가 확인하는 순서

1. `http://127.0.0.1:18182` 로그인. 로그인 값은 `.env.microservices`의 BOOTSTRAP_ADMIN 항목을 로컬에서 확인한다.
2. 합성 데모 문서의 비밀번호 변경 주기를 질문해 90일 답변·실제 문서 출처·검토 여부를 확인한다. 문서가 조직 실제 정책이 아니라 합성임을 유지한다.
3. 대화 새로고침 후 답변·출처·모드가 복원되는지 확인한다.
4. 재현 가능한 전체 검증은 아래 명령. 합성 문서를 새로 업로드하고 실제 파싱·임베딩·검색·Bedrock·이력·재색인·삭제 제외를 검사한다. 호출 비용이 소액 발생한다.

```powershell
.\local\.venv\Scripts\python.exe hybrid/tools/verify_bedrock_stack.py --no-build
```

앱 한도는 모델 호출 전 차단을 테스트하므로 유료 모델을 호출하지 않고 검증할 수 있다. 자동 테스트에 실제 Redis 동시성 40건/허용 7건, 일·월·예약 금액 한도, 실패 예약 유지, 개인정보 미기록, 출력 상한, HTTP 검색 전환을 포함한다.

CloudWatch의 현재 API는 `AWS/BedrockMantle` 네임스페이스다. `Inferences`, `TotalInputTokens`, `TotalOutputTokens`, `InferenceClientErrors`를 사용한다. `AWS/Bedrock`의 Runtime 지표와 혼동하지 않는다. Mantle은 사전 거절 429와 지연 지표를 제공하지 않으므로 앱의 capacity 사유·요청 지연은 로컬에서 관측한다. 준비된 경보는 콘솔 상태만 표시하며 이메일 동작은 Budgets에 구성된다. 실제 앱 집계 카운터만 전송·재조회했다. 이 경로는 수동 1회 실행이며 상시 원본 로그 전송 에이전트가 아니다. 로컬 Prometheus 수집과 Bedrock 자체 CloudWatch 지표는 계속 동작한다.

주 1회 실제 청구·토큰·예약량·질문당 호출 수·저장량을 비교하고 월말 추정이 예산을 넘으면 검증 빈도·보관량부터 조정한다. `aws_finops.py costs`는 Cost Explorer 유료 API 조회가 발생할 수 있어 자동 반복하지 않는다. 그 보고서는 계정 서비스별 비용이며 제품별 정확한 원가 배분이 아니다. 공유 계정에서는 비용 할당 태그를 활성화하고 추론 프로젝트·모델 차원을 추가한다.

## 품질과 포트폴리오

Qwen3-32B API를 썼다는 사실만으로 로컬보다 품질이 높다고 단정하지 않는다. 동일 문서·질문·검색 결과로 로컬 모델과 비교해 정답률, 출처 정확성, 근거 없는 질문의 거절률, 응답 p50/p95, 질문당 실제 토큰·호출 수를 측정한다. 현재 1개 합성 샘플 성공은 연결 증거이며 성능 우위 증거는 아니다.

자소서에는 구현과 검증이 끝난 범위만 쓴다: “문서·검색·권한은 로컬에 유지하고 외부 추론을 허용 목록과 공유 사용량 한도로 제어했습니다. 모든 추론 단계에 예약을 적용하고 한도 초과 시 근거 문서 검색으로 전환했으며, 실제 AWS 연결과 Redis 동시성·장애 테스트로 동작을 확인했습니다.” ECR/S3/Budgets는 이번에 실제 계정 배포·설정 조회를 마쳤다. 게시한 이미지는 conversation 한 종류이며 다른 3개 서비스 저장소는 준비 상태다. 제품 전체의 다중 호스트 배포·고가용성을 검증한 것으로 확대하지 않는다.

## 근거

- https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sign-in.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/monitoring-mantle-metrics.html
- https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html
- https://docs.aws.amazon.com/AmazonECR/latest/userguide/lifecycle_policy_examples.html
- https://aws.amazon.com/bedrock/pricing/


## 2026-10-19 실제 배포·검증 결과

- 도쿄 CloudFormation `secure-doc-hybrid-baseline`: 13개 자원 생성 완료. 기본 설정 16개와 TLS·수명주기·대시보드 추가 7개 검사 통과.
- AWS Budgets: 계정 월 30 USD·Bedrock 월 20 USD, 제공한 이메일 등록과 각 4개 알림 조회 확인. 실제 이메일 수신까지 시험한 것은 아니다.
- 전체 서비스 회귀 테스트 119개 + OCI 게시 검증 회귀 테스트 3개 통과. 별도 가짜 클라우드 어댑터 테스트와 실제 AWS E2E를 구분한다.
- FinOps 활성화된 실제 스택 E2E 8개 검사 통과. 이번 실행은 기존 데모 문서가 남아 있어 빈 지식베이스 검사는 생략했고, 앞선 빈 지식베이스 포함 실행은 9개 통과했다.
- 로컬 관측 검사 7개 통과: 3개 서비스 scrape, FinOps 경보 로드, 실제 수치, Grafana 7개 패널과 데이터 연결·로그인 보호, Alertmanager 준비 상태.
- CloudWatch 집계 전송과 재조회 통과. AWS Mantle의 네이티브 지표도 실제 요청·토큰 데이터가 조회됨.
- ECR conversation immutable 태그 `release-053e5d82d63c4ce6` 게시. OCI index digest까지 로컬과 동일함을 확인했다. Docker 버전에 따라 image.Id가 config digest 또는 OCI index digest이므로 두 형식을 구분한다.
- S3 `releases/`에 93,457,920바이트 이미지 아카이브와 manifest 게시. 서버 SHA-256 확인. 이미지 서명·서명 검증까지 구현한 것은 아니다.
- 루트 배포 기본 차단을 유지한다. 사용자의 명시적 승인으로 이번 13개 자원 템플릿 SHA-256에만 제한한 예외 플래그를 사용했다. 이후 일반 작업에는 IAM 개발 신원을 사용한다.

확인 화면:

- 서비스: http://127.0.0.1:18182
- Grafana: http://127.0.0.1:13102/d/secure-doc-hybrid-finops
- Prometheus: http://127.0.0.1:29202
- AWS CloudWatch `SecureDoc-Hybrid` 대시보드: 도쿄 리전
- AWS Budgets: `secure-doc-hybrid-account`, `secure-doc-hybrid-bedrock`

Grafana의 관리자 값은 무시되는 `.env.microservices`의 `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`에 있다. 채팅·문서에는 비밀번호를 넣지 않았다.

```powershell
.\local\.venv\Scripts\python.exe hybrid/tools/verify_hybrid_monitoring.py
.\local\.venv\Scripts\python.exe hybrid/tools/aws_finops.py verify
.\local\.venv\Scripts\python.exe hybrid/tools/aws_operations.py --apply
.\local\.venv\Scripts\python.exe hybrid/tools/aws_release.py --release hybrid/.releases/conversation-finops-20261019
```

마지막 명령은 게시 계획·로컬 검증만 수행한다. 게시에는 `--apply`가 필요하다. ECR·S3는 기존 검증 스택의 실행 경로에 동기 의존성으로 연결하지 않았다. AWS가 끊겨도 로컬에 적재된 이미지로 실행하며, 새 버전 배포 때만 원격 아티팩트 경로를 사용한다. 현재 단일 로컬 호스트·단일 상태 저장 인스턴스 구성은 호스트 고가용성을 제공하지 않는다.


## 이미지 스캔 검토와 운영 승격 제한

conversation 이미지의 ECR Basic 스캔이 완료되었으며 **High 3·Medium 9·Low 3, Critical 0**이 보고되었다. [공개 스캔 요약](evidence/conversation-image-scan-20261019.json)에 설치 패키지와 CVE를 기록했다. 이 이미지는 내부 합성 데모용이며 운영 승격 검사를 통과하지 못했다. 게시·체크섬 검증 성공을 취약점 해결 완료로 해석하지 않는다.

| CVE | 패키지 | Debian stable 확인 결과 |
|---|---|---|
| CVE-2026-19499 | glibc 2.41-12+deb13u4 | trixie 취약 상태, 수정 버전은 sid/forky 쪽. stable 수정 없음 |
| CVE-2026-5435 | glibc 2.41-12+deb13u4 | trixie 취약 상태, stable 수정 없음 |
| CVE-2026-85091 | zlib 1.3.dfsg+really1.3.1-1 | trixie 취약 상태, 패키지 수정 없음. upstream 영향 범위 논의가 있어 자체적으로 오탐 처리하지 않음 |

glibc 두 건의 Debian 분류는 `no-dsa` / Minor issue이지만 ECR High 결과를 지우거나 무시하지 않았다. 애플리케이션에서 취약 함수까지 도달 가능한지는 검증하지 않았으며, 영향이 없다고 단정하지 않는다. 안정 배포판에 sid의 libc를 섞어 호환성을 깨는 업데이트를 하지 않았다. stable 보안 수정 또는 검증 가능한 새 베이스가 나오면 재빌드 → 전체 서비스 검증 → 새 불변 릴리스 → 재스캔 순서로 적용한다.

기본 승격 검사는 스캔 미완료 또는 High/Critical이 있으면 종료 코드 2를 반환한다. 취약점을 자동 수정하는 도구가 아니며 ECR Basic은 Python 의존성까지 검사하지 않는다. 전체 공급망 검사를 위해 별도의 언어 패키지 스캐너와 이미지 서명 검증이 추가로 필요하다.

```powershell
.\local\.venv\Scripts\python.exe hybrid/tools/check_aws_image.py --tag release-053e5d82d63c4ce6
```

근거: [glibc CVE-2026-19499](https://security-tracker.debian.org/tracker/CVE-2026-19499), [glibc CVE-2026-5435](https://security-tracker.debian.org/tracker/CVE-2026-5435), [zlib CVE-2026-85091](https://security-tracker.debian.org/tracker/CVE-2026-85091).
