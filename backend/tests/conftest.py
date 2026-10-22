"""Portable test defaults that do not depend on a developer's private .env file."""

import os


os.environ.setdefault("APP_ENVIRONMENT", "test")
os.environ.setdefault("LLM_MODEL", "test-model")
os.environ.setdefault("LLM_API_KEY", "test-llm-api-key")
os.environ.setdefault("API_ACCESS_KEY", "test-service-api-key")
