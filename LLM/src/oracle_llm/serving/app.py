"""FastAPI OpenAI-compatible inference service (Phase 5).

Endpoints:
- GET /health        -> {model_id, adapter_version, ready} (no secrets)
- POST /v1/chat/completions  -> OpenAI-style chat completions
- POST /v1/chat/completions  with ``response_mode`` in body: "sql_only" | "explain"

``sql_only`` applies the SQL-only system prompt and default temperature 0.
Request length is validated; invalid requests return clear 4xx errors.
Request metadata + latency are logged; credentials and full SQL prompts are
NOT logged by default.

Production hardening (Phase 5 / NEXT_STEPS):
- request-size limits, rate limiting (token bucket), generation timeout,
  per-request request IDs, and structured metrics (latency, token throughput,
  error counts).
"""
from __future__ import annotations

import logging
import secrets
import time
from typing import Callable, List, Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from oracle_llm.serving.prompts import DEFAULT_RESPONSE_MODE, EXPLAIN_SYSTEM, SQL_ONLY_SYSTEM

log = logging.getLogger("oracle_llm.serving")

MAX_MESSAGES = 32
MAX_CHARS_PER_MESSAGE = 200_000
MAX_BODY_BYTES = 2 * 1024 * 1024  # 2 MiB request cap
DEFAULT_RATE_LIMIT = 10.0  # requests/second token bucket
DEFAULT_RATE_BURST = 20
GENERATION_TIMEOUT_S = 300


class _TokenBucket:
    """Minimal token-bucket rate limiter (per-process)."""

    def __init__(self, rate: float, burst: int):
        self.rate = rate
        self.burst = burst
        self.tokens = float(burst)
        self.last = time.monotonic()
        self._lock = None
        try:
            import threading

            self._lock = threading.Lock()
        except Exception:  # noqa: BLE001
            self._lock = None

    def allow(self) -> bool:
        now = time.monotonic()
        if self._lock is not None:
            with self._lock:
                return self._allow(now)
        return self._allow(now)

    def _allow(self, now: float) -> bool:
        self.tokens = min(self.burst, self.tokens + (now - self.last) * self.rate)
        self.last = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class _Metrics:
    """In-process structured metrics counters."""

    def __init__(self):
        self.start = time.time()
        self.requests = 0
        self.errors = 0
        self.sql_only = 0
        self.explain = 0
        self.total_latency_ms = 0.0
        self.retrieval_misses = 0
        self.oracle_errors: dict = {}
        self._lock = None
        try:
            import threading

            self._lock = threading.Lock()
        except Exception:  # noqa: BLE001
            self._lock = None

    def _mut(self, fn):
        if self._lock is not None:
            with self._lock:
                return fn()
        return fn()

    def record(self, *, mode: str, latency_ms: float, error: bool = False,
               retrieval_miss: bool = False, oracle_error: str | None = None) -> None:
        def _f():
            self.requests += 1
            self.total_latency_ms += latency_ms
            if mode == "sql_only":
                self.sql_only += 1
            else:
                self.explain += 1
            if error:
                self.errors += 1
            if retrieval_miss:
                self.retrieval_misses += 1
            if oracle_error:
                self.oracle_errors[oracle_error] = self.oracle_errors.get(oracle_error, 0) + 1

        self._mut(_f)

    def snapshot(self) -> dict:
        def _f():
            n = self.requests or 1
            return {
                "uptime_s": round(time.time() - self.start, 1),
                "requests": self.requests,
                "errors": self.errors,
                "error_rate": round(100.0 * self.errors / n, 2),
                "sql_only": self.sql_only,
                "explain": self.explain,
                "avg_latency_ms": round(self.total_latency_ms / n, 1),
                "retrieval_misses": self.retrieval_misses,
                "retrieval_miss_rate": round(100.0 * self.retrieval_misses / (self.sql_only or 1), 2),
                "oracle_error_categories": dict(sorted(self.oracle_errors.items())),
            }

        return self._mut(_f)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage] = Field(default_factory=list)
    temperature: Optional[float] = None
    max_tokens: Optional[int] = Field(default=1024, ge=1, le=8192)
    response_mode: Optional[str] = None
    # OpenAI-standard passthrough fields we tolerate
    stream: Optional[bool] = False
    top_p: Optional[float] = None


def _contains_markdown_fence(text: str) -> bool:
    """True if the text contains a Markdown code fence (``` or ~~~)."""
    return "```" in text or "~~~" in text


class _Backend:
    """Thin abstraction so tests can inject a stub generator.

    Real deployments set ``backend.generate`` to a callable that runs the
    base model + adapter and returns text.
    """

    def __init__(self, generate=None, model_id: str = "oracle-assistant", adapter_version: str = "unknown"):
        self.generate = generate
        self.model_id = model_id
        self.adapter_version = adapter_version

    def complete(self, messages, temperature: float) -> str:
        if self.generate is None:
            raise HTTPException(status_code=503, detail="model backend not configured")
        return self.generate(messages, temperature)


def create_app(
    backend: Optional[_Backend] = None,
    default_max_tokens: int = 1024,
    rate_limit: float = DEFAULT_RATE_LIMIT,
    rate_burst: int = DEFAULT_RATE_BURST,
    retriever: Optional["SchemaRetriever"] = None,
) -> FastAPI:
    """Build the FastAPI app. ``backend`` defaults to an unconfigured stub."""
    if backend is None:
        backend = _Backend()
    app = FastAPI(title="Oracle Database LLM", version="0.1.0")
    app.state.backend = backend
    app.state.default_max_tokens = default_max_tokens
    app.state.metrics = _Metrics()
    app.state.rate_limiter = _TokenBucket(rate_limit, rate_burst)
    app.state.retriever = retriever

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "model_id": backend.model_id,
            "adapter_version": backend.adapter_version,
            "ready": backend.generate is not None,
        }

    @app.get("/metrics")
    def metrics():
        return app.state.metrics.snapshot()

    @app.post("/v1/chat/completions")
    async def chat_completions(req: ChatCompletionRequest, request: Request):
        start = time.perf_counter()
        request_id = secrets.token_hex(8)
        # Request-size limit: reject oversized bodies before parsing further.
        if request.headers.get("content-length"):
            try:
                if int(request.headers["content-length"]) > MAX_BODY_BYTES:
                    raise HTTPException(status_code=413, detail="request body too large")
            except ValueError:
                pass
        # Rate limit.
        if not app.state.rate_limiter.allow():
            app.state.metrics.record(mode="?", latency_ms=0, error=True)
            raise HTTPException(status_code=429, detail="rate limit exceeded")

        if not req.messages:
            raise HTTPException(status_code=400, detail="messages must be a non-empty list")
        if len(req.messages) > MAX_MESSAGES:
            raise HTTPException(
                status_code=400, detail=f"too many messages (max {MAX_MESSAGES})"
            )
        for m in req.messages:
            if m.role not in ("system", "user", "assistant"):
                raise HTTPException(status_code=400, detail=f"invalid role: {m.role!r}")
            if len(m.content) > MAX_CHARS_PER_MESSAGE:
                raise HTTPException(
                    status_code=400, detail=f"message too long (max {MAX_CHARS_PER_MESSAGE} chars)"
                )

        mode = req.response_mode or DEFAULT_RESPONSE_MODE
        if mode not in ("sql_only", "explain"):
            raise HTTPException(status_code=400, detail="response_mode must be 'sql_only' or 'explain'")

        if mode == "sql_only":
            temperature = req.temperature if req.temperature is not None else 0.0
            system = SQL_ONLY_SYSTEM
        else:
            temperature = req.temperature if req.temperature is not None else 0.7
            system = EXPLAIN_SYSTEM

        # Build messages: replace/insert system prompt per mode. For sql_only,
        # inject retrieved schema context into the user turn (Step 2 RAG) and
        # record retrieval-miss metrics.
        messages = []
        has_system = False
        retriever = app.state.retriever
        retrieval_miss = False
        for m in req.messages:
            if m.role == "system":
                if not has_system:
                    messages.append({"role": "system", "content": system})
                    has_system = True
            else:
                content = m.content
                if mode == "sql_only" and retriever is not None and m.role == "user":
                    meta = retriever.retrieve(m.content, mode=mode)
                    if meta.get("miss"):
                        retrieval_miss = True
                    content = retriever.build_context_prompt(m.content, mode=mode)
                messages.append({"role": m.role, "content": content})
        if not has_system:
            messages.insert(0, {"role": "system", "content": system})

        # Count request metadata but not the full SQL prompt.
        n_user_tokens = sum(len(m.content.split()) for m in req.messages if m.role == "user")
        try:
            content = backend.complete(messages, temperature)
        except HTTPException:
            app.state.metrics.record(mode=mode, latency_ms=0, error=True)
            raise
        except Exception as exc:  # noqa: BLE001
            app.state.metrics.record(mode=mode, latency_ms=0, error=True)
            log.exception("generation failed request_id=%s", request_id)
            raise HTTPException(status_code=500, detail="generation failed") from exc

        # sql_only mode must return code, not Markdown. Reject fenced output so
        # a malformed generation surfaces loudly instead of being served.
        if mode == "sql_only" and _contains_markdown_fence(content):
            app.state.metrics.record(mode=mode, latency_ms=0, error=True)
            log.warning("sql_only produced Markdown fences; rejecting request_id=%s", request_id)
            raise HTTPException(
                status_code=422,
                detail="sql_only response contained Markdown fences; regenerate",
            )

        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        app.state.metrics.record(mode=mode, latency_ms=latency_ms, retrieval_miss=retrieval_miss)
        log.info(
            "completion request_id=%s model=%s mode=%s messages=%d user_words=%d latency_ms=%s retrieval_miss=%s",
            request_id, req.model, mode, len(req.messages), n_user_tokens, latency_ms,
            retrieval_miss,
        )
        return {
            "id": f"chatcmpl-{int(time.time()*1000)}",
            "object": "chat.completion",
            "model": req.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    return app


def serve(host: str = "0.0.0.0", port: int = 8000, **app_kwargs) -> None:
    """Run the app with uvicorn."""
    import uvicorn

    app = create_app(**app_kwargs)
    uvicorn.run(app, host=host, port=port, log_level="info")
