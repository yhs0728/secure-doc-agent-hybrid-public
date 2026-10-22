# 2026년 10월 18일 코드 리뷰 수정

## 변경 내용

- 테스트 DB provisioning에 역할 소유권 검사를 추가했다. `_test` DB에서도 운영 역할이나 다른 테스트 DB 소유 역할을 덮어쓰지 않는다. 같은 전용 테스트 DB는 재실행할 수 있다. 테스트는 별도 PostgreSQL 인스턴스를 사용한다.
- 예상하지 못한 500 응답도 요청 ID, 응답 지표와 완료 로그를 남긴다.
- 작업의 최종 상태를 기준으로 `secure_doc_knowledge_unresolved_jobs`를 계산한다. 재시도 성공 후 과거 FAILED 이력 때문에 경보가 유지되는 문제를 수정했다.
- 대화 이력은 기본 2,000자, 최대 8,000자의 문자 예산으로 제한한다. `LLM_HISTORY_MAX_CHARACTERS=0`이면 비활성화한다. 현재 질문은 보존하며 토큰 예산과는 구분한다.
- CSV 필드 한도를 8,000,000자로 명시하고 CSV 파싱 실패를 영구 오류로 분류한다.
- 세 버전에 추출 8,000,000자·10,000청크·DOCX 확장 100MiB·10,000 ZIP 항목 제한과 영구 오류 분류를 반영했다.
- Compose 래퍼가 `--profile` 같은 Docker Compose 옵션을 하위 명령 앞에서도 전달하도록 수정했다. 래퍼의 `--validation`, `-f/--file`은 Compose 옵션 시작 전에 둔다.

## 실행 예시

```bash
python3 tools/compose.py --profile monitoring config --quiet
python3 tools/compose.py --profile monitoring up -d cadvisor prometheus grafana alertmanager
python3 tools/compose.py --validation --profile monitoring config --quiet
```

수정된 애플리케이션을 실행하려면 이미지를 다시 빌드하고 컨테이너를 재생성한다. Prometheus는 변경된 규칙을 다시 불러와야 한다. 클라우드 버전의 실제 AWS 호출은 이번 회귀 테스트에 포함하지 않았다.

## 검증

격리된 임시 PostgreSQL·Redis로 서버 전체 테스트를 실행했다. local 108개, hybrid 77개, multicloud 77개가 모두 통과했고 skip은 없다. 변경한 Python 파일의 Ruff 검사도 통과했다. 회귀 테스트는 `microservices/tests/test_review_regressions.py`에 있다. 테스트용 컨테이너·볼륨은 검증 후 제거했다.

local은 새 identity·knowledge·conversation 이미지를 빌드해 API와 worker 컨테이너에 적용했다. readiness HTTP 200, 서비스 상태, 새 gauge 수집과 Prometheus 경보 규칙의 health=ok를 확인했다. hybrid·multicloud는 테스트·설정 반영까지이며 실제 클라우드 배포는 수행하지 않았다.
