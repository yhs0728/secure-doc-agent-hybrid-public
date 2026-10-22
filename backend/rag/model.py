from langchain_openai import ChatOpenAI

from config.settings import Settings


def create_chat_model(
    settings: Settings,
) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=(
            settings.llm_api_key.get_secret_value()
        ),
        base_url=settings.llm_base_url,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout_seconds,
        max_tokens=64,
        # A retry can multiply the user-visible timeout and leave Ollama
        # generating abandoned responses. The API returns one clear error and
        # lets the caller decide whether the request is safe to retry.
        max_retries=0,
        extra_body={
            "think": settings.llm_thinking,
            "max_tokens": 64,
            # Ollama's OpenAI-compatible endpoint may ignore the newer
            # max_completion_tokens field emitted by OpenAI clients. Enforce
            # a native generation bound as well.
            "options": {"num_predict": 64},
        },
    )
