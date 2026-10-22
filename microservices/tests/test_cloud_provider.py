import pytest
from conversation_service.llm_config import answer_token_limit, provider_options


@pytest.fixture
def bedrock(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("LLM_MODEL", "qwen.qwen3-32b")
    monkeypatch.setenv("LLM_API_KEY", "test-bedrock-key")
    monkeypatch.setenv(
        "LLM_BASE_URL", "https://bedrock-mantle.ap-northeast-1.api.aws/v1"
    )


def test_bedrock_uses_cloud_options_without_ollama_fields(bedrock, monkeypatch):
    monkeypatch.setenv("LLM_ANSWER_MAX_TOKENS", "512")
    options = provider_options()
    assert options["model"] == "qwen.qwen3-32b"
    assert options["max_tokens"] == 512
    assert options["max_retries"] == 0
    assert "extra_body" not in options


@pytest.mark.parametrize(
    "url",
    [
        "http://bedrock-mantle.ap-northeast-1.api.aws/v1",
        "https://bedrock-mantle.ap-northeast-1.api.aws.attacker.invalid/v1",
        "https://key:secret@bedrock-mantle.ap-northeast-1.api.aws/v1",
        "https://bedrock-mantle.ap-northeast-1.api.aws/v1?key=secret",
        "https://bedrock-mantle.ap-northeast-1.api.aws/incorrect",
    ],
)
def test_bedrock_rejects_unsafe_or_invalid_endpoint(bedrock, monkeypatch, url):
    monkeypatch.setenv("LLM_BASE_URL", url)
    with pytest.raises(ValueError):
        provider_options()


@pytest.mark.parametrize("limit", ["0", "4097", "invalid"])
def test_invalid_answer_budget_fails_before_model_call(monkeypatch, limit):
    monkeypatch.setenv("LLM_ANSWER_MAX_TOKENS", limit)
    with pytest.raises(ValueError):
        answer_token_limit()


def test_generation_receives_answer_budget(bedrock, monkeypatch):
    from conversation_service.rag.generator import create_rag_chain
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    monkeypatch.setenv("LLM_ANSWER_MAX_TOKENS", "768")
    bound = []

    class Model(FakeListChatModel):
        def bind(self, **kwargs):
            bound.append(kwargs)
            return super().bind(**kwargs)

    chain = create_rag_chain(Model(responses=["90 days"]))
    assert chain.invoke({"question": "How often?", "context": "90 days"}) == "90 days"
    assert bound == [{"max_tokens": 768}]
