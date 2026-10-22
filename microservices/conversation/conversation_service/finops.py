"""Shared admission ledger, not an AWS billing meter or guaranteed dollar cap.

Reserve before every external model call. Failed/unknown calls retain reservations.
UTC periods, aggregate counters only: no prompts, answers, documents or user IDs.
"""

import json
import math
import os
from datetime import datetime, timezone
from decimal import Decimal
from functools import lru_cache

from redis import RedisError

RESERVE = """
for i=1,2 do
  local calls=tonumber(redis.call('HGET',KEYS[i],'calls') or '0')
  local amount=tonumber(redis.call('HGET',KEYS[i],'reserved_microusd') or '0')
  if calls>=tonumber(ARGV[i]) or amount+tonumber(ARGV[5])>tonumber(ARGV[i+2]) then
    return 0
  end
end
for i=1,2 do
  redis.call('HINCRBY',KEYS[i],'calls',1)
  redis.call('HINCRBY',KEYS[i],'reserved_microusd',ARGV[5])
  redis.call('EXPIRE',KEYS[i],3888000)
end
return 1
"""


class FinOpsDenied(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def enabled():
    return os.getenv("FINOPS_ENABLED", "false").lower() == "true"


def positive(name, default, *, decimal=False):
    value = (
        Decimal(os.getenv(name, str(default)))
        if decimal
        else int(os.getenv(name, str(default)))
    )
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return value


class Ledger:
    def __init__(
        self,
        client,
        namespace="secure-doc",
        *,
        daily_calls=60,
        monthly_calls=600,
        daily_microusd=1_000_000,
        monthly_microusd=20_000_000,
        input_rate=Decimal(1),
        output_rate=Decimal(5),
        max_input_bytes=32000,
        max_output=1024,
    ):
        values = (
            daily_calls,
            monthly_calls,
            daily_microusd,
            monthly_microusd,
            input_rate,
            output_rate,
            max_input_bytes,
            max_output,
        )
        if any(not math.isfinite(x) or x <= 0 for x in values):
            raise ValueError("Invalid FinOps limits")
        self.client, self.namespace = client, namespace
        self.limits = (daily_calls, monthly_calls, daily_microusd, monthly_microusd)
        self.input_rate, self.output_rate = input_rate, output_rate
        self.max_input_bytes, self.max_output = max_input_bytes, max_output

    def keys(self):
        seconds, _ = self.client.time()
        now = datetime.fromtimestamp(seconds, timezone.utc)
        base = self.namespace + ":{finops}:"
        return [base + now.strftime("%Y-%m-%d"), base + now.strftime("%Y-%m")]

    def reserve(self, value, max_output):
        if type(max_output) is not int or not 1 <= max_output <= self.max_output:
            raise ValueError("Output reservation must be within the configured token cap")
        # Content length is a conservative control proxy, not a tokenizer.
        if hasattr(value, "to_messages"):
            payload = [m.model_dump(mode="json") for m in value.to_messages()]
        else:
            payload = value
        size = len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf8"))
        if size > self.max_input_bytes:
            raise FinOpsDenied("finops_input_limit")
        amount = math.ceil(
            (size + 1024) * self.input_rate + max_output * self.output_rate
        )
        try:
            keys = self.keys()
            if not self.client.eval(RESERVE, 2, *keys, *self.limits, amount):
                raise FinOpsDenied("finops_budget")
        except RedisError:
            raise FinOpsDenied("finops_unavailable") from None
        return keys

    def record(self, keys, result):
        usage = getattr(result, "usage_metadata", None) or {}
        # Reservations are deliberately never refunded, including missing usage.
        try:
            with self.client.pipeline(transaction=True) as pipe:
                for key in keys:
                    pipe.hincrby(key, "completed", 1)
                    complete = True
                    for field in ("input_tokens", "output_tokens"):
                        value = usage.get(field)
                        if type(value) is int and value >= 0:
                            pipe.hincrby(key, field, value)
                        else:
                            complete = False
                    if not complete:
                        pipe.hincrby(key, "usage_missing", 1)
                pipe.execute()
        except RedisError:
            # The reservation was already committed; do not repeat a paid call.
            pass

    def snapshot(self):
        return dict(
            zip(("day", "month"), [self.client.hgetall(k) for k in self.keys()])
        )


@lru_cache
def ledger():
    from .admission import admission

    controller = admission()
    if not hasattr(controller, "client"):
        raise ValueError("FinOps requires shared Redis")
    return Ledger(
        controller.client,
        os.getenv("REDIS_NAMESPACE", "secure-doc"),
        daily_calls=positive("FINOPS_DAILY_CALL_LIMIT", 60),
        monthly_calls=positive("FINOPS_MONTHLY_CALL_LIMIT", 600),
        daily_microusd=int(
            positive("FINOPS_DAILY_CONTROL_USD", 1, decimal=True) * 1_000_000
        ),
        monthly_microusd=int(
            positive("FINOPS_MONTHLY_CONTROL_USD", 20, decimal=True) * 1_000_000
        ),
        input_rate=positive("FINOPS_CONTROL_INPUT_USD_PER_M", 1, decimal=True),
        output_rate=positive("FINOPS_CONTROL_OUTPUT_USD_PER_M", 5, decimal=True),
        max_input_bytes=positive("FINOPS_MAX_INPUT_BYTES", 32000),
        max_output=positive("FINOPS_MAX_OUTPUT_TOKENS", 1024),
    )


def metrics():
    if not enabled():
        return "secure_doc_finops_enabled 0\n"
    try:
        snapshot = ledger().snapshot()
        lines = ["secure_doc_finops_enabled 1", "secure_doc_finops_available 1"]
        for period, counters in snapshot.items():
            for field in (
                "calls",
                "completed",
                "reserved_microusd",
                "input_tokens",
                "output_tokens",
                "usage_missing",
            ):
                lines.append(
                    f'secure_doc_finops_{field}{{period="{period}"}} {int(counters.get(field, 0))}'
                )
        return "\n".join(lines) + "\n"
    except RedisError:
        return "secure_doc_finops_enabled 1\nsecure_doc_finops_available 0\n"
