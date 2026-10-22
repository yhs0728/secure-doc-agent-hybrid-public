"""Replica-wide RAG admission, with owned Redis leases and fail-closed renewal.

Leases control application admission, not the lifetime of a remote LLM computation.
The LLM server must enforce its own hard execution limit during network partitions.
"""

import logging
import os
import threading
import time
from contextvars import ContextVar
from functools import lru_cache
from uuid import uuid4

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

logger = logging.getLogger(__name__)
active_lease = ContextVar("rag_admission_lease", default=None)

ACQUIRE = """
local tm=redis.call('TIME'); local now=tm[1]*1000+math.floor(tm[2]/1000)
redis.call('ZREMRANGEBYSCORE',KEYS[1],'-inf',now)
if redis.call('ZCARD',KEYS[1])>=tonumber(ARGV[1]) then return 0 end
redis.call('ZADD',KEYS[1],now+tonumber(ARGV[2]),ARGV[3])
redis.call('PEXPIRE',KEYS[1],tonumber(ARGV[2])*2)
return 1
"""
RENEW = """
local tm=redis.call('TIME'); local now=tm[1]*1000+math.floor(tm[2]/1000)
local expires=redis.call('ZSCORE',KEYS[1],ARGV[1])
if not expires or tonumber(expires)<=now then return 0 end
redis.call('ZADD',KEYS[1],now+tonumber(ARGV[2]),ARGV[1])
redis.call('PEXPIRE',KEYS[1],tonumber(ARGV[2])*2)
return 1
"""
VALID = """
local tm=redis.call('TIME'); local now=tm[1]*1000+math.floor(tm[2]/1000)
local expires=redis.call('ZSCORE',KEYS[1],ARGV[1])
if expires and tonumber(expires)>now then return 1 end
return 0
"""
RATE = """
local count=tonumber(redis.call('GET',KEYS[1]) or '0')
if count>=tonumber(ARGV[1]) then return redis.call('PTTL',KEYS[1]) end
count=redis.call('INCR',KEYS[1])
if count==1 then redis.call('PEXPIRE',KEYS[1],ARGV[2]) end
return -1
"""


class CapacityBusy(Exception):
    pass


class ControlUnavailable(Exception):
    pass


class RateLimited(Exception):
    def __init__(self, retry_after):
        self.retry_after = retry_after


class RedisLease:
    def __init__(self, controller, token):
        self.controller = controller
        self.token = token
        self.stop = threading.Event()
        self.lost = threading.Event()
        self.thread = threading.Thread(target=self.renew, daemon=True)
        self.thread.start()

    def renew(self):
        while not self.stop.wait(self.controller.ttl_ms / 3000):
            try:
                if not self.controller.client.eval(
                    RENEW, 1, self.controller.key, self.token, self.controller.ttl_ms
                ):
                    self.lost.set()
                    return
            except redis.RedisError:
                self.lost.set()
                return

    def ensure_valid(self):
        try:
            valid = not self.lost.is_set() and self.controller.client.eval(
                VALID, 1, self.controller.key, self.token
            )
        except redis.RedisError as exc:
            self.lost.set()
            raise ControlUnavailable() from exc
        if not valid:
            raise ControlUnavailable()

    def release(self):
        self.stop.set()
        self.thread.join(timeout=3)
        try:
            # An old request can remove only its own token, never a replacement owner.
            self.controller.client.zrem(self.controller.key, self.token)
        except redis.RedisError:
            logger.warning(
                "Redis admission release unavailable; owned lease will expire"
            )


class RedisAdmission:
    def __init__(
        self,
        client,
        *,
        limit=1,
        ttl_ms=900_000,
        namespace="secure-doc",
        pool="default",
        rate_limit=30,
        rate_window_ms=60_000,
    ):
        if limit < 1 or ttl_ms < 300 or rate_limit < 1 or rate_window_ms < 1:
            raise ValueError("Invalid admission limits")
        self.client = client
        self.limit = limit
        self.ttl_ms = ttl_ms
        self.namespace = namespace
        self.key = f"{namespace}:{{llm-{pool}}}:slots"
        self.rate_limit = rate_limit
        self.rate_window_ms = rate_window_ms

    def enforce_rate(self, context):
        key = f"{self.namespace}:rate:{context['workspace_id']}:{context['user_id']}"
        try:
            wait = self.client.eval(RATE, 1, key, self.rate_limit, self.rate_window_ms)
        except redis.RedisError as exc:
            raise ControlUnavailable() from exc
        if wait >= 0:
            raise RateLimited(max(1, (wait + 999) // 1000))

    def acquire(self, timeout):
        deadline = time.monotonic() + timeout
        token = uuid4().hex
        while True:
            try:
                if self.client.eval(
                    ACQUIRE, 1, self.key, self.limit, self.ttl_ms, token
                ):
                    return RedisLease(self, token)
            except redis.RedisError as exc:
                raise ControlUnavailable() from exc
            if time.monotonic() >= deadline:
                raise CapacityBusy()
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))


class LocalLease:
    def __init__(self, semaphore):
        self.semaphore = semaphore

    def ensure_valid(self):
        return None

    def release(self):
        self.semaphore.release()


class LocalAdmission:
    """Explicit isolated-test/development mode; never an automatic Redis fallback."""

    def __init__(self, limit):
        self.semaphore = threading.BoundedSemaphore(limit)

    def enforce_rate(self, context):
        return None

    def acquire(self, timeout):
        if not self.semaphore.acquire(timeout=timeout):
            raise CapacityBusy()
        return LocalLease(self.semaphore)


@lru_cache
def admission():
    limit = int(os.getenv("LLM_MAX_CONCURRENCY", "1"))
    backend = os.getenv("CAPACITY_BACKEND", "redis")
    if backend == "memory":
        if os.getenv("APP_ENVIRONMENT", "development") == "production":
            raise RuntimeError("Production requires shared Redis admission")
        return LocalAdmission(limit)
    if backend != "redis":
        raise RuntimeError("CAPACITY_BACKEND must be redis or memory")
    password = os.environ.get("REDIS_PASSWORD")
    if not password:
        raise RuntimeError("REDIS_PASSWORD must be configured")
    client = redis.Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        password=password,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
        retry=Retry(NoBackoff(), 0),
        ssl=os.getenv("REDIS_SSL", "false").lower() == "true",
    )
    return RedisAdmission(
        client,
        limit=limit,
        ttl_ms=int(os.getenv("LLM_SLOT_TTL_SECONDS", "900")) * 1000,
        namespace=os.getenv("REDIS_NAMESPACE", "secure-doc"),
        pool=os.getenv("LLM_CAPACITY_POOL", "default"),
        rate_limit=int(os.getenv("RAG_RATE_LIMIT_REQUESTS", "30")),
        rate_window_ms=int(os.getenv("RAG_RATE_LIMIT_WINDOW_SECONDS", "60")) * 1000,
    )


class GuardedModel:
    """Check admission before each LLM call, including graph retries/validation calls."""

    def __init__(self, model, lease):
        self.model = model
        self.lease = lease

    def bind(self, **kwargs):
        from langchain_core.runnables import RunnableLambda

        def check(value):
            self.lease.ensure_valid()
            return value

        return RunnableLambda(check) | self.model.bind(**kwargs)
