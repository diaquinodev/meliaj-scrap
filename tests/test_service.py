import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from intelligence.api import Settings, create_app
from intelligence.contracts import Draft, ProductInput
from intelligence.providers import Completion, DemoProvider, ProviderTimeout, ProviderUnavailable
from intelligence.service import CircuitBreaker, DraftService, ServiceError

TOKEN = "test-token-not-for-production"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PRODUCT = {"name": "Body feminino", "details": "Cor preta."}


def settings(**kwargs):
    return Settings(api_token=TOKEN, **kwargs)


def test_missing_credentials_fail_at_startup():
    with pytest.raises(ValidationError):
        Settings()
    with pytest.raises(ValidationError):
        settings(mode="gemini")
    with pytest.raises(ValidationError):
        settings(input_price_per_million=float("nan"))
    with pytest.raises(ValidationError) as caught:
        settings(mode="gemini", gemini_key="")
    assert TOKEN not in str(caught.value)


def test_auth_validation_health_and_metrics():
    with TestClient(create_app(settings())) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").json()["provider_checked"] is False
        assert client.post("/v1/drafts", json=PRODUCT).status_code == 401
        assert client.get("/metrics").status_code == 401
        assert client.post("/v1/drafts", headers=AUTH, json={"name": "x"}).status_code == 422
        response = client.post("/v1/drafts", headers=AUTH, json=PRODUCT)
        assert response.status_code == 200
        body = response.json()
        assert body["mode"] == "demo"
        assert body["draft"]["requires_review"] is True
        assert body["draft"]["material"] is None
        assert body["estimated_cost_usd"] is None
        assert body["input_tokens"] is None
        metrics = client.get("/metrics", headers=AUTH).text
        assert 'llm_requests_total{outcome="success"} 1.0' in metrics
        assert body["request_id"] not in metrics  # sem labels de alta cardinalidade


@pytest.mark.parametrize("error,status,code", [
    (ProviderTimeout("secret"), 504, "timeout"),
    (ProviderUnavailable("secret"), 503, "provider_error"),
    (RuntimeError("secret"), 500, "internal_error"),
])
def test_provider_errors_do_not_expose_secrets(error, status, code):
    provider = Mock()
    provider.generate.side_effect = error
    with TestClient(create_app(settings(), provider)) as client:
        response = client.post("/v1/drafts", headers=AUTH, json=PRODUCT)
        assert response.status_code == status
        assert response.json()["error"] == code
        assert "secret" not in response.text
        assert response.headers["x-request-id"] == response.json()["request_id"]


@pytest.mark.parametrize("payload", [
    "not json",
    json.dumps({"title": "x" * 61, "description": "Descrição válida"}),
    json.dumps({"title": "Body feminino", "description": "<script>alert(1)</script>"}),
    json.dumps({"title": "Body feminino", "description": "Descrição válida", "material": "Algodão"}),
    json.dumps({"title": "Body feminino", "description": "Descrição válida", "requires_review": False}),
])
def test_invalid_or_ungrounded_outputs_are_rejected(payload):
    provider = Mock()
    provider.generate.return_value = Completion(payload, 20, 10)
    app = create_app(settings(input_price_per_million=1, output_price_per_million=2), provider)
    with TestClient(app) as client:
        response = client.post("/v1/drafts", headers=AUTH, json=PRODUCT)
        assert response.status_code == 502
        assert app.state.service.cost._value.get() == pytest.approx(.00004)


def test_usage_cost_and_safe_logs(caplog):
    provider = Mock()
    provider.generate.return_value = Completion(Draft(
        title="Body feminino", description="Descrição confirmada.").model_dump_json(), 100, 50)
    service = DraftService(provider, settings(input_price_per_million=2, output_price_per_million=4))
    with caplog.at_level("INFO", logger="intelligence"):
        result = service.generate(ProductInput(name="Body feminino", details="sensitive-customer-data"))
    assert result.estimated_cost_usd == pytest.approx(.0004)
    assert "sensitive-customer-data" not in caplog.text
    assert TOKEN not in caplog.text
    assert result.request_id in caplog.text


def test_breaker_opens_and_has_one_half_open_probe():
    now = [0.0]
    breaker = CircuitBreaker(2, 30, lambda: now[0])
    breaker.failure()
    assert breaker.allow()
    breaker.failure()
    assert not breaker.allow()
    now[0] = 31
    assert breaker.allow()
    assert not breaker.allow()
    breaker.failure()
    assert not breaker.allow()
    now[0] = 62
    assert breaker.allow()
    breaker.success()
    assert breaker.allow()


def test_circuit_stops_calls_after_repeated_errors():
    provider = Mock()
    provider.generate.side_effect = ProviderUnavailable("failure")
    service = DraftService(provider, settings(failure_threshold=2))
    for expected in ["provider_error", "provider_error", "circuit_open"]:
        with pytest.raises(ServiceError) as caught:
            service.generate(ProductInput(**PRODUCT))
        assert caught.value.code == expected
    assert provider.generate.call_count == 2


def test_concurrency_limit_rejects_extra_work_and_recovers():
    entered, release = threading.Event(), threading.Event()

    class Blocking:
        def generate(self, product):
            entered.set()
            assert release.wait(5)
            return DemoProvider().generate(product)

    service = DraftService(Blocking(), settings(max_concurrency=1))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.generate, ProductInput(**PRODUCT))
        assert entered.wait(5)
        try:
            with pytest.raises(ServiceError) as caught:
                service.generate(ProductInput(**PRODUCT))
            assert caught.value.code == "busy"
        finally:
            release.set()
        assert future.result().draft.requires_review
    assert service.generate(ProductInput(**PRODUCT)).draft.requires_review
