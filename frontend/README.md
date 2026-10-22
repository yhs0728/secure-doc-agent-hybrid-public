# SecureDoc Web

기본 배포는 마이크로서비스 Gateway입니다. 외부 API URL은 유지하고 Nginx에서
인증·문서·대화 서비스로 분기합니다. 문서의 실제 `processing_status`를 표시하고
처리 중인 문서와 재색인 상태를 주기적으로 갱신합니다.
현재 대화 목록 조회·재열기·새 대화·새로고침 복원도 구현되어 있습니다.
실행은 루트에서 `python tools/compose.py up -d --build`입니다.
변경된 구조·API 계약은 [서비스 구성](../microservices/README.md)을 참고하세요.

SecureDoc Web은 답변 자체보다 답변의 근거를 빠르게 확인하도록 설계한 Evidence Workspace입니다.

## UX 구조

- 데스크톱: 문서 탐색, 질문·답변, 근거 확인을 한 화면의 3열로 배치합니다.
- 모바일: 대화 맥락은 유지하고 선택한 근거를 접근성 Dialog로 표시합니다.
- 답변마다 실제 API citation을 표시하며, 문서명·페이지 수 외의 원문 문단은 만들지 않습니다.
- `requires_human_review` 응답은 경고로 노출해 근거가 부족한 답변의 오용을 줄입니다.
- VIEWER, EDITOR, ADMIN 역할에 따라 업로드·삭제·인덱스 갱신·사용자 관리 기능을 구분합니다.

## 기술 선택

- React 19 + TypeScript strict: 역할별 화면과 비동기 상태를 타입으로 관리합니다.
- Vite: 빠른 로컬 개발과 Nginx에서 제공할 정적 번들을 만듭니다.
- React Router: 로그인, 질문, 문서, 인덱스, 사용자, 프로필 화면을 분리합니다.
- TanStack Query: 서버 상태 캐시와 mutation 후 무효화를 담당합니다.
- React Hook Form + Zod: 로그인·사용자 생성·비밀번호 변경 검증을 공유합니다.
- Tailwind CSS + Radix UI primitives: 일관된 UI와 키보드·스크린리더 접근성을 제공합니다.
- Vitest + Testing Library + Playwright: 유틸리티와 실제 사용자 흐름을 검증합니다.

의존성은 `package.json`과 `package-lock.json`에 정확한 버전으로 고정합니다.

## 로컬 개발

요구 사항은 Node.js 22 이상과 실행 중인 FastAPI 서버입니다.

```powershell
npm ci
npm run dev
```

기본 주소는 `http://localhost:15172`이며 Vite가 `/api`를 `http://localhost:18082`으로
proxy합니다. 프록시 대상 변경은 셸 환경 변수 `VITE_API_PROXY_TARGET`, 개발 포트 변경은 `VITE_DEV_SERVER_PORT`를 사용합니다. 브라우저에서 직접 호출할 API 주소는 `.env.example`을 참고해
`VITE_API_BASE_URL`을 설정합니다.

## 검증

```powershell
npm run typecheck
npm run test
npm run build
npm run test:e2e
npm audit
```

Playwright 테스트는 API를 route mock으로 고정해 로그인, 근거 기반 답변, 데스크톱
근거 패널, 모바일 근거 Dialog를 반복 검증합니다.

## 배포

루트에서 `python tools/compose.py up -d --build`를 실행하면 multi-stage Dockerfile이 정적
번들을 만든 뒤 Nginx에 복사합니다. Nginx는 `/`에서 SPA를 제공하고 `/api/*`를
FastAPI로 전달하므로 CORS 없이 같은 origin을 사용합니다.

## 현재 API 경계

- 질문 API의 citation은 현재 파일명 배열입니다. 원문 문단, 페이지 번호, score가
  추가되면 우측 근거 패널을 실제 passage viewer로 확장할 수 있습니다.
- 인증 토큰은 새로고침 유지가 필요한 동안 `sessionStorage`에 보관합니다. 인터넷에
  공개하기 전에는 backend-for-frontend 또는 FastAPI의 Secure·HttpOnly·SameSite
  cookie와 refresh rotation으로 교체하는 것이 권장됩니다.
- ingestion job 진행률과 대화 목록 API가 없으므로 가짜 진행률이나 영속 대화 목록을
  표시하지 않습니다. 문서 처리 결과는 인덱스 상태에서 확인합니다.
