# Bedrock 연결

## 로컬에서 연결 준비

```powershell
python tools/prepare_microservices_env.py
Copy-Item .env.bedrock.example .env.bedrock
# .env.bedrock의 BEDROCK_API_KEY에 발급받은 Bedrock API key 입력
python tools/compose.py config --quiet
python tools/compose.py up -d --build
```

Compose 프로젝트는 이 저장소 전용이며 원본 로컬 볼륨과 자동 공유하지 않습니다.
현재 연결은 Bedrock API key 인증과 Mantle Chat Completions를 사용합니다. 기본 리전은 도쿄,
모델 ID는 `qwen.qwen3-32b`, base URL은 `https://bedrock-mantle.ap-northeast-1.api.aws/v1`입니다.
원하면 AWS의 최신 모델 지원표와 선택한 엔드포인트를 확인하고 리전을 변경합니다.
`LLM_PROVIDER=bedrock`은 HTTPS AWS endpoint를 검증하며 Ollama 전용 요청 필드를 보내지 않습니다.
응답용 한도는 512토큰이며 `LLM_ANSWER_MAX_TOKENS`로 16~4096 범위에서 변경할 수 있습니다.
관련성·출처·근거 판정용 토큰 한도는 기존의 짧은 설정을 유지합니다.

API key를 브라우저·Git·로그에 노출하지 않습니다. 운영 키는 Secret 저장소에 주입하고 주기적으로
교체합니다. 다른 서비스에 배포 권한이나 AWS 관리자 권한을 주지 않습니다.
원본은 저장소에 남지만 질문·검색 문맥·이전 대화 일부는 Bedrock 처리 리전으로 전송됩니다.
모델별 thinking·출력 형식·토큰 사용량은 실제 계정 연결 후 검증해야 합니다.

## 실제 연결 검증

```powershell
python tools/verify_full_stack.py --base-url http://127.0.0.1:18082 --report .microservice-tests/bedrock-e2e.json
```

위 검증은 실제 API 호출 요금이 발생합니다. 이 저장소 초기 분리 과정에서는 클라우드 키를
복사하거나 새로 발급하지 않았으며 실제 Bedrock E2E를 실행했다고 주장하지 않습니다.
기존 로컬 검증 기록과 새 클라우드 테스트 결과를 구분합니다.

공식 기준:
- https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-qwen-qwen3-32b.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/inference-chat-completions.html

AWS Budgets 알림과 실제 월별 토큰 집계를 함께 사용합니다. 현재 Redis는 동시 실행과
사용자별 요청 속도 제한을 제공하며 월 비용을 자동으로 차단하지는 않습니다.

## 작업 폴더

현재 위치: `C:\llm-study\secure-doc-agent\hybrid`.
게이트웨이: `http://127.0.0.1:18082`, 프런트 개발 서버: `http://127.0.0.1:15172`.
검증 전용 스택은 `python tools/compose.py --validation up -d --build`로 실행하고,
`python tools/verify_full_stack.py`로 검증합니다(기본 주소 `18182`).
일반 스택 검증은 `--base-url http://127.0.0.1:18082`를 지정합니다.
WSL에서는 `python3 tools/compose.py`를 사용합니다.

개발 환경과 작업 공간 안내: `C:\llm-study\secure-doc-agent\local\WORKSPACE.md`.
공통 Python 환경의 현재 위치는 `local/.venv`이며, 각 저장소에 별도 환경을 만들 수도 있습니다.


## 하이브리드 장애 격리·전송 정책

외부 추론은 기본 차단이며 허용된 작업공간만 호출합니다. 키가 없어도 검색 전용으로 기동할 수 있습니다. 장애 시 문서 발췌 전환과 대화 이력 표시, 프로세스별 호출 차단, 로컬 이미지 보관·복원을 추가했습니다. [운영 절차](docs/hybrid-operations.md), [검증 기록](docs/hybrid-validation-20261019.md), [자소서·면접 문안](docs/cover-letter-hybrid.md)을 참고하세요.


## AWS 배포와 FinOps

도쿄 ECR·S3·CloudWatch·Budgets 실제 배포, 앱 공유 호출 한도와 Grafana, 검증 방법은 [운영 및 FinOps 안내](docs/hybrid-finops.md)를 참고하세요.
