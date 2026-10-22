# SecureDoc Backend

FastAPI API, 비동기 Worker, RAG pipeline, 데이터베이스 migration을 포함하는 독립적인
Python 애플리케이션입니다. Python 명령은 이 디렉터리를 작업 디렉터리로 사용합니다.

## 로컬 실행

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

기본 로컬 fallback은 파일 저장소와 FAISS를 사용할 수 있습니다. PostgreSQL, S3 API,
OpenSearch를 포함한 통합 환경은 저장소 루트에서 `docker compose up -d --build`로
실행합니다.

## 테스트

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```

저장소 루트에 기존 `.venv`가 있는 개발 환경에서는 다음 명령도 사용할 수 있습니다.

```powershell
..\.venv\Scripts\python.exe -m pytest -q
```

실제 MiniLM과 Ollama를 사용하는 E2E는 명시적으로 활성화합니다.

```powershell
$env:RUN_REAL_E2E = "1"
.\.venv\Scripts\python.exe -m pytest tests/e2e/test_real_e2e.py -v -s
```

## 주요 디렉터리

- `app/`: FastAPI endpoint, 인증, middleware, runtime 조립
- `services/`: 문서·질문·인덱스 application service
- `ingestion/`, `retrieval/`, `rag/`, `graph/`: RAG pipeline
- `database/`: SQLAlchemy model, repository, Alembic, Worker
- `integrations/`: Object Storage와 OpenSearch adapter
- `tests/`: 단위·통합·실제 E2E·부하 테스트
- `scripts/`: 설치, 백업·복구, 부하 시험 자동화
- `docs/`: ERD, 운영, 확장 설계

## 컨테이너

`backend/Dockerfile`의 build context는 `backend/`로 한정됩니다. 따라서 프론트엔드
소스나 Node dependency가 백엔드 이미지에 포함되지 않습니다.
