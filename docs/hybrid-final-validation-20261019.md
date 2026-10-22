# Hybrid 최종 검증 및 보완 — 2026-10-19

Git 게시 전 현재 활성 마이크로서비스·프런트엔드·실제 AWS 합성 데이터 흐름을 다시 검증했다. [기계 판독용 결과](evidence/hybrid-final-verification-20261019.json)를 함께 보관한다.

| 검사 | 결과 | 범위 |
|---|---|---|
| 백엔드 | 143 passed, 실패·skip 0 | 일회용 실제 PostgreSQL·Redis; 클라우드 어댑터는 테스트 대역 |
| HTTP 프로세스 smoke | PASS | 독립 프로세스 3개, 로그인·문서 큐·이력·서비스 중단 격리 |
| 프런트엔드 | 타입·프로덕션 빌드 PASS, Vitest 2 passed | 실제 번들 생성 |
| Chromium | 8 passed | 로그인·이력·출처·모바일·검색 전환; API 모의 응답 |
| 실제 AWS 흐름 | 8개 검사 PASS | 실제 업로드·임베딩·검색·Bedrock·대화 이력·원자적 재색인·삭제 제외 |
| AWS 구성 | 18개 검사 PASS | 기존 자원 조회; 예산 범위·통화·주기·임계값·이메일·S3·ECR·CloudWatch |
| 관측 | 7개 검사 PASS | 서비스 수집·FinOps 경보·Grafana 실제 데이터·로그인 보호 |
| 정적 검사 | Ruff·variant·git diff check PASS | microservices 및 tools |
| 비밀 값 검사 | 발견 0 | 후보 파일 320개, 실제 비밀 설정 값·알림 이메일 및 키 패턴 검사 |

프런트엔드에는 별도 lint 스크립트가 없으므로 타입 검사와 빌드·Vitest·Chromium을 검증 기준으로 사용했다. 테스트 수는 AWS 호출 수나 부하 처리량이 아니다. 최신 단일 합성 실행의 RAG 지연 6.422초·업로드 준비 95.844초는 동시 로컬 테스트/빌드 부하가 있는 환경의 관찰값이며 p95·SLA·모델 성능 우위로 해석하지 않는다. 기존 합성 데모 문서가 남아 있어 이번에는 빈 지식베이스 분기를 실행하지 않았다. 해당 분기는 앞선 별도 실행과 자동 회귀 검사에서 검증했다.

## 보완 사항

- 출처 검증 파싱 실패 시 모델 응답 본문이 로그에 노출되지 않도록 오류 유형만 기록한다. 성공 응답도 본문을 debug 로그에 남기지 않는다.
- 일부 토큰 필드가 없거나 잘못된 경우 실제 사용량 누락으로 집계한다. 유효한 필드의 집계와 선예약은 유지한다.
- 잘못된 출력 토큰 예약은 Redis에 접근하기 전에 거부한다.
- 예산 알림 개수 외에 실제/예상 지출의 임계값, 백분율, 비용 범위, 통화와 주기를 확인한다.
- 문서 작업자 시작 시 저장소 403/5xx/연결 장애를 새 버킷 생성 요청으로 바꾸지 않는다. HeadBucket HTTP 404에서만 생성한다.
- 실제 DB·Redis를 일회용 컨테이너로 준비하고 정리하는 재현 도구를 저장소에 추가했다. 생성한 라벨의 컨테이너만 제거한다.
- GitHub Actions에 프런트엔드 검사와 백엔드 정적 검사를 추가했다. AWS 키 없이 CI 검사를 실행하도록 유지한다.

## 재현

저장소의 의존성이 설치된 Python과 Docker가 필요하다. 저장소 안에서:

```powershell
python tools/run_service_checks.py
python -m ruff check microservices tools
python tools/verify_variant.py
```

프런트엔드 폴더에서:

```powershell
npm ci
npm run build
npm test
npx playwright install chromium
npm run test:e2e
```

실제 AWS 합성 검사에는 로컬의 무시되는 `.env.microservices`·`.env.bedrock`가 필요하며 호출 비용이 발생한다. `.env.finops`는 CLI 임시 프로파일과 예산 설정용이며 소스에 포함하지 않는다.

```powershell
python tools/verify_bedrock_stack.py --no-build
python tools/aws_finops.py verify
python tools/verify_hybrid_monitoring.py
```

검증 보고서와 코드 게시를 운영 배포 승인으로 해석하지 않는다. 게시된 ECR 릴리스의 High 3건은 [FinOps 안내의 이미지 검토](hybrid-finops.md)에 기록한 미해결 상태다. 이 검사에서는 새 AWS 인프라를 생성하거나 기존 이미지 스캔 결과를 무시하지 않았다. 이미지 서명, 언어 패키지 전체 검사, 호스트 HA와 로컬 대비 품질 비교는 완료 범위가 아니다.
