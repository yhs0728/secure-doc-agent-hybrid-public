"""Local egress policy and bounded external inference, independent of AWS SDKs."""

import os
import threading
import time
from collections import Counter
from functools import lru_cache
from uuid import UUID

from langchain_core.runnables import RunnableLambda
from openai import APIConnectionError, APIStatusError, APITimeoutError

from . import finops


class InferenceUnavailable(Exception):
    def __init__(self, reason="provider_unavailable"):
        super().__init__(reason)
        self.reason = reason


class InferenceDenied(Exception):
    """Authentication/configuration errors are not disguised as an outage."""


def external_provider():
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    if not provider:
        provider = "ollama" if ":11434" in os.getenv("LLM_BASE_URL", "") else "openai"
    return provider != "ollama"


def allowed_workspaces():
    # No wildcard or request-controlled override. Empty is deny-all.
    raw = os.getenv("HYBRID_EXTERNAL_WORKSPACES", "")
    return frozenset(
        str(UUID(value.strip())) for value in raw.split(",") if value.strip()
    )


def external_allowed(context):
    return str(UUID(context["workspace_id"])) in allowed_workspaces()


class CircuitBreaker:
    """Process-local. Epochs prevent stale calls closing a newly opened circuit."""

    def __init__(self, threshold=3, cooldown=30, clock=time.monotonic):
        if threshold < 1 or cooldown <= 0:
            raise ValueError("Invalid circuit settings")
        self.threshold, self.cooldown, self.clock = threshold, cooldown, clock
        self.lock = threading.Lock()
        self.failures = 0
        self.epoch = 0
        self.opened_at = None
        self.probing = False

    def enter(self):
        with self.lock:
            if self.opened_at is not None:
                if self.clock() - self.opened_at < self.cooldown or self.probing:
                    raise InferenceUnavailable("circuit_open")
                self.probing = True
            return self.epoch

    def finish(self, epoch, failed=False):
        with self.lock:
            if epoch != self.epoch:
                return
            if failed:
                self.failures += 1
                if self.probing or self.failures >= self.threshold:
                    self.opened_at = self.clock()
                    self.probing = False
                    self.epoch += 1
            else:
                self.failures = 0
                self.opened_at = None
                self.probing = False

    def metrics(self):
        with self.lock:
            return int(self.opened_at is not None)


@lru_cache
def circuit():
    return CircuitBreaker(
        threshold=int(os.getenv("HYBRID_CIRCUIT_FAILURES", "3")),
        cooldown=float(os.getenv("HYBRID_CIRCUIT_COOLDOWN_SECONDS", "30")),
    )


class ExternalModel:
    """Guard all graph stages; retain failures even when a judge node catches them.

    Budget prevents starting further calls, not cancellation of an in-flight call.
    HTTP timeout bounds each call. No retries or automatic external provider switching.
    """

    def __init__(self, model, context, *, budget=90, clock=time.monotonic):
        if budget <= 0:
            raise ValueError("Inference budget must be positive")
        self.model, self.context, self.clock = model, dict(context), clock
        self.deadline = clock() + budget
        self.failure = None
        self.calls = 0

    def bind(self, **kwargs):
        if finops.enabled():
            maximum = finops.ledger().max_output
            kwargs["max_tokens"] = min(int(kwargs.get("max_tokens", maximum)), maximum)
            if kwargs["max_tokens"] < 1:
                raise ValueError("max_tokens must be positive")
        bound = self.model.bind(**kwargs)

        def invoke(value, config=None):
            if not external_allowed(self.context):
                self.failure = InferenceUnavailable("external_policy")
            if self.failure:
                raise self.failure
            if self.clock() >= self.deadline:
                self.failure = InferenceUnavailable("inference_budget")
                raise self.failure
            try:
                if finops.enabled():
                    if self.calls >= 8:
                        raise finops.FinOpsDenied("finops_question_limit")
                    keys = finops.ledger().reserve(value, kwargs["max_tokens"])
                    self.calls += 1
                result = bound.invoke(value, config=config)
                if finops.enabled():
                    finops.ledger().record(keys, result)
                return result
            except finops.FinOpsDenied as error:
                self.failure = InferenceUnavailable(error.reason)
            except APITimeoutError:
                self.failure = InferenceUnavailable("provider_timeout")
            except APIConnectionError:
                self.failure = InferenceUnavailable("provider_unavailable")
            except APIStatusError as error:
                if error.status_code in (408, 429) or error.status_code >= 500:
                    self.failure = InferenceUnavailable(
                        "provider_capacity"
                        if error.status_code == 429
                        else "provider_unavailable"
                    )
                else:
                    self.failure = InferenceDenied("PROVIDER_CONFIGURATION_ERROR")
            # Provider response bodies/prompts are never included in our exception.
            raise self.failure from None

        return RunnableLambda(invoke)


_outcomes = Counter()
_lock = threading.Lock()


def record_outcome(mode, reason):
    with _lock:
        _outcomes[(mode, reason)] += 1


def metrics():
    with _lock:
        lines = [
            f'secure_doc_hybrid_responses_total{{mode="{mode}",reason="{reason}"}} {count}'
            for (mode, reason), count in sorted(_outcomes.items())
        ]
    lines.append(f"secure_doc_hybrid_circuit_open {circuit().metrics()}")
    return "\n".join(lines) + "\n"
