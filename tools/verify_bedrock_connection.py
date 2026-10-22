"""Live Bedrock + RAG graph verification with an explicitly synthetic document only.

Reads the ignored .env.bedrock; never prints keys, provider errors or generated text.
No cloud infrastructure is provisioned. Real inference incurs token usage charges.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "microservices/conversation"))


def verify(config_path, report):
    from conversation_service.graph.workflow import build_rag_workflow
    from conversation_service.hybrid import ExternalModel
    from conversation_service.llm_config import provider_options
    from langchain_core.documents import Document
    from langchain_openai import ChatOpenAI

    config = dotenv_values(config_path) if config_path.is_file() else {}
    key = config.get("BEDROCK_API_KEY") or os.getenv("BEDROCK_API_KEY")
    if not key or key.startswith(("replace-", "your-", "<")):
        raise ValueError("BEDROCK_API_KEY is not configured in hybrid/.env.bedrock")
    region = config.get("AWS_REGION") or os.getenv("AWS_REGION", "ap-northeast-1")
    model_id = config.get("BEDROCK_MODEL_ID") or os.getenv(
        "BEDROCK_MODEL_ID", "qwen.qwen3-32b"
    )
    # Explicitly synthetic workspace; does not authorize any real application workspace.
    workspace = str(uuid4())
    os.environ.update(
        {
            "LLM_PROVIDER": "bedrock",
            "LLM_BASE_URL": f"https://bedrock-mantle.{region}.api.aws/v1",
            "LLM_API_KEY": key,
            "LLM_MODEL": model_id,
            "LLM_ANSWER_MAX_TOKENS": "512",
            "LLM_TIMEOUT_SECONDS": "30",
            "HYBRID_EXTERNAL_WORKSPACES": workspace,
        }
    )
    document = Document(
        page_content="SecureDoc 합성 테스트 정책입니다. 테스트 계정의 비밀번호 변경 주기는 90일입니다. 실제 조직이나 고객의 정책이 아닙니다.",
        metadata={
            "source": "synthetic-bedrock-policy.txt",
            "document_id": "synthetic-only",
            "chunk_id": "synthetic-only:0",
        },
    )

    class SyntheticRetriever:
        def invoke(self, query):
            return [document]

    selected = ExternalModel(
        ChatOpenAI(**provider_options()), {"workspace_id": workspace}, budget=90
    )
    started = time.monotonic()
    result = build_rag_workflow(SyntheticRetriever(), selected).invoke(
        {"question": "합성 테스트 계정의 비밀번호 변경 주기는 며칠인가요?"}
    )
    if selected.failure:
        raise selected.failure
    passed = (
        not result.get("requires_human_review", True)
        and "synthetic-bedrock-policy.txt" in result.get("citations", [])
        and "90" in result.get("answer", "")
    )
    output = {
        "passed": passed,
        "region": region,
        "model_id": model_id,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "actual_bedrock_calls": True,
        "input": "synthetic document only",
        "scope": "real inference through production RAG graph; retriever is a synthetic fixture, not deployed storage",
        "infrastructure_provisioned": False,
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf8")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / ".env.bedrock")
    parser.add_argument(
        "--report", type=Path, default=ROOT / ".microservice-tests/bedrock-live.json"
    )
    args = parser.parse_args()
    try:
        result = verify(args.config, args.report)
    except Exception as error:  # noqa: BLE001 - redact provider errors at the CLI boundary
        # No error message/traceback: SDK errors can contain response or request data.
        print(
            json.dumps(
                {
                    "passed": False,
                    "error_type": type(error).__name__,
                    "configuration_present": args.config.is_file(),
                }
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
