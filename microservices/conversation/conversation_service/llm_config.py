"""Provider-specific request settings; AWS authentication remains server-side."""

import os
import re
from urllib.parse import urlsplit

from .platform import required


def answer_token_limit():
    value = int(os.getenv("LLM_ANSWER_MAX_TOKENS", "64"))
    if not 16 <= value <= 4096:
        raise ValueError("LLM_ANSWER_MAX_TOKENS must be between 16 and 4096")
    return value


def provider_options():
    limit = answer_token_limit()
    options = {
        "model": required("LLM_MODEL"),
        "api_key": required("LLM_API_KEY"),
        "temperature": float(os.getenv("LLM_TEMPERATURE", "0")),
        "timeout": float(os.getenv("LLM_TIMEOUT_SECONDS", "30")),
        "max_retries": 0,
        "max_tokens": limit,
    }
    if not 0 < options["timeout"] <= 300:
        raise ValueError("LLM_TIMEOUT_SECONDS must be in (0, 300]")
    base_url = os.getenv("LLM_BASE_URL")
    if base_url:
        options["base_url"] = base_url
    provider = os.getenv(
        "LLM_PROVIDER", "ollama" if ":11434" in (base_url or "") else "openai"
    )
    if provider == "bedrock":
        url = urlsplit(required("LLM_BASE_URL"))
        mantle = re.fullmatch(
            r"bedrock-mantle\.[a-z0-9-]+\.api\.aws", url.hostname or ""
        )
        runtime = re.fullmatch(
            r"bedrock-runtime\.[a-z0-9-]+\.amazonaws\.com", url.hostname or ""
        )
        valid_path = url.path.rstrip("/") in (
            ("/v1", "/openai/v1") if mantle else ("/openai/v1",)
        )
        if (
            url.scheme != "https"
            or not (mantle or runtime)
            or not valid_path
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.port not in (None, 443)
        ):
            raise ValueError(
                "Bedrock requires an authenticated AWS HTTPS Chat Completions endpoint"
            )
    elif provider == "ollama":
        options["extra_body"] = {
            "think": os.getenv("LLM_THINKING", "false").lower() == "true",
            "max_tokens": limit,
            "options": {"num_predict": limit},
        }
    elif provider != "openai":
        raise ValueError("LLM_PROVIDER must be ollama, openai, or bedrock")
    return options
