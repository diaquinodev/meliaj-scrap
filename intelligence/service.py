"""Validação, limite de concorrência, circuit breaker e métricas por instância."""

import json
import logging
import threading
import time
from uuid import uuid4

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from pydantic import ValidationError

from .contracts import Draft, DraftResponse
from .prompts import PROMPT_VERSION
from .providers import ProviderTimeout, ProviderUnavailable

logger = logging.getLogger("intelligence")


class ServiceError(RuntimeError):
    def __init__(self, status_code, code, request_id):
        self.status_code, self.code, self.request_id = status_code, code, request_id
        super().__init__(code)


class CircuitBreaker:
    """Estado por processo. Após cooldown permite uma única requisição de prova."""

    def __init__(self, threshold=3, cooldown=30.0, clock=time.monotonic):
        self.threshold, self.cooldown, self.clock = threshold, cooldown, clock
        self.failures, self.opened_at, self.probing = 0, None, False
        self.lock = threading.Lock()

    def allow(self):
        with self.lock:
            if self.opened_at is None:
                return True
            if self.clock() - self.opened_at < self.cooldown or self.probing:
                return False
            self.probing = True
            return True

    def success(self):
        with self.lock:
            self.failures, self.opened_at, self.probing = 0, None, False

    def failure(self):
        with self.lock:
            self.failures += 1
            if self.probing or self.failures >= self.threshold:
                self.opened_at = self.clock()
            self.probing = False


class DraftService:
    def __init__(self, provider, settings, *, clock=time.monotonic):
        self.provider, self.settings, self.clock = provider, settings, clock
        self.slots = threading.BoundedSemaphore(settings.max_concurrency)
        self.breaker = CircuitBreaker(settings.failure_threshold, settings.cooldown_seconds, clock)
        self.registry = CollectorRegistry()
        self.requests = Counter("llm_requests_total", "Tentativas de geração autenticadas", ["outcome"], registry=self.registry)
        self.duration = Histogram("llm_request_duration_seconds", "Latência total de geração", buckets=(.1, .5, 1, 2, 5, 10, 20, 30, 60), registry=self.registry)
        self.tokens = Counter("llm_tokens_total", "Tokens reportados pelo provedor", ["direction"], registry=self.registry)
        self.cost = Counter("llm_estimated_cost_usd_total", "Estimativa pelas tarifas configuradas", registry=self.registry)
        self.missing_usage = Counter("llm_usage_missing_total", "Respostas sem contagem completa de tokens", registry=self.registry)
        self.inflight = Gauge("llm_inflight", "Gerações em andamento", registry=self.registry)
        # Séries zeradas existem antes da primeira falha para consultas de SLO.
        for outcome in ("success", "busy", "circuit_open", "timeout", "provider_error", "invalid_output", "internal_error"):
            self.requests.labels(outcome)

    def generate(self, product):
        request_id, started = str(uuid4()), self.clock()
        outcome, acquired = "internal_error", False
        try:
            acquired = self.slots.acquire(blocking=False)
            if not acquired:
                outcome = "busy"
                raise ServiceError(503, outcome, request_id)
            if not self.breaker.allow():
                outcome = "circuit_open"
                raise ServiceError(503, outcome, request_id)
            self.inflight.inc()
            try:
                completion = self.provider.generate(product)
                cost = self._record_usage(completion)
                draft = Draft.model_validate_json(completion.text)
                if draft.material != product.material:
                    raise ValueError("Material deve coincidir com o dado fornecido.")
            except ProviderTimeout:
                self.breaker.failure()
                outcome = "timeout"
                raise ServiceError(504, outcome, request_id) from None
            except ProviderUnavailable:
                self.breaker.failure()
                outcome = "provider_error"
                raise ServiceError(503, outcome, request_id) from None
            except (ValidationError, ValueError):
                self.breaker.failure()
                outcome = "invalid_output"
                raise ServiceError(502, outcome, request_id) from None
            except Exception:
                self.breaker.failure()
                raise ServiceError(500, "internal_error", request_id) from None
            finally:
                self.inflight.dec()
            self.breaker.success()
            outcome = "success"
            return DraftResponse(
                request_id=request_id, mode=self.settings.mode,
                model=self.settings.model if self.settings.mode == "gemini" else "deterministic-fixture",
                prompt_version=PROMPT_VERSION, latency_ms=round((self.clock() - started) * 1000, 2),
                input_tokens=completion.input_tokens, output_tokens=completion.output_tokens,
                estimated_cost_usd=cost, draft=draft,
            )
        finally:
            if acquired:
                self.slots.release()
            elapsed = self.clock() - started
            self.requests.labels(outcome).inc()
            self.duration.observe(elapsed)
            # Nunca registrar prompt, resposta, token de acesso ou chave do provedor.
            logger.info(json.dumps({"event": "draft_completed", "request_id": request_id,
                                    "outcome": outcome, "latency_ms": round(elapsed * 1000, 2),
                                    "prompt_version": PROMPT_VERSION, "mode": self.settings.mode}))

    def _record_usage(self, completion):
        for direction, count in (("input", completion.input_tokens), ("output", completion.output_tokens)):
            if count is not None:
                self.tokens.labels(direction).inc(count)
        if completion.input_tokens is None or completion.output_tokens is None:
            self.missing_usage.inc()
            return None
        if self.settings.input_price_per_million is None or self.settings.output_price_per_million is None:
            return None
        cost = (completion.input_tokens * self.settings.input_price_per_million
                + completion.output_tokens * self.settings.output_price_per_million) / 1000000
        self.cost.inc(cost)
        return cost
