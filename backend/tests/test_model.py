from config.settings import Settings
from rag import model as model_module


def test_settings_reads_environment(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "LLM_MODEL",
        "test-model",
    )
    monkeypatch.setenv(
        "LLM_API_KEY",
        "test-api-key",
    )
    monkeypatch.setenv(
        "API_ACCESS_KEY",
        "test-service-api-key",
    )
    monkeypatch.setenv(
        "LLM_BASE_URL",
        "http://localhost:8000/v1",
    )
    monkeypatch.setenv(
        "LLM_THINKING",
        "false",
    )

    settings = Settings(
        _env_file=None,
    )

    assert settings.llm_model == "test-model"

    assert settings.llm_thinking is False
    assert (
        settings.llm_api_key.get_secret_value()
        == "test-api-key"
    )

    assert settings.llm_base_url == (
        "http://localhost:8000/v1"
    )


def test_create_chat_model(
    monkeypatch,
) -> None:
    received_arguments: dict[str, object] = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs) -> None:
            received_arguments.update(kwargs)

    monkeypatch.setattr(
        model_module,
        "ChatOpenAI",
        FakeChatOpenAI,
    )

    settings = Settings(
        llm_model="test-model",
        llm_api_key="test-api-key",
        api_access_key="test-service-api-key",
        llm_base_url="http://localhost:8000/v1",
        llm_temperature=0.0,
        llm_timeout_seconds=30.0,
        llm_thinking=False,
    )

    model_module.create_chat_model(
        settings=settings,
    )

    assert received_arguments["model"] == (
        "test-model"
    )

    assert received_arguments["api_key"] == (
        "test-api-key"
    )

    assert received_arguments["base_url"] == (
        "http://localhost:8000/v1"
    )
    
    assert received_arguments["max_tokens"] == 64
    assert received_arguments["extra_body"] == {
        "think": False,
        "max_tokens": 64,
        "options": {"num_predict": 64},
    }

    assert received_arguments["temperature"] == 0.0
    assert received_arguments["timeout"] == 30.0
    assert received_arguments["max_retries"] == 0
    
