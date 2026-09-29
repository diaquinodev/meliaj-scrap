"""API de rascunhos. Execute: uvicorn intelligence.api:create_app --factory."""

from contextlib import asynccontextmanager
import hmac
import logging
import os
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import DraftResponse, ProductInput
from .providers import DemoProvider, GeminiProvider
from .service import DraftService, ServiceError


class Settings(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, hide_input_in_errors=True)
    mode: Literal["demo", "gemini"] = "demo"
    api_token: str = Field(min_length=16, repr=False)
    gemini_key: str = Field(default="", repr=False)
    model: str = Field(default="gemini-2.5-flash", min_length=1)
    timeout_seconds: float = Field(default=20, gt=0, le=60)
    max_output_tokens: int = Field(default=2048, ge=128, le=8192)
    max_concurrency: int = Field(default=4, ge=1, le=32)
    failure_threshold: int = Field(default=3, ge=1, le=20)
    cooldown_seconds: float = Field(default=30, gt=0, le=300)
    input_price_per_million: float | None = Field(default=None, ge=0)
    output_price_per_million: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_key(self):
        if self.mode == "gemini" and not self.gemini_key.strip():
            raise ValueError("GEMINI_API_KEY é obrigatória no modo gemini.")
        return self

    @classmethod
    def from_env(cls):
        mapping = {
            "mode": "LLM_MODE", "api_token": "SERVICE_API_TOKEN", "gemini_key": "GEMINI_API_KEY",
            "model": "GEMINI_MODEL", "timeout_seconds": "LLM_TIMEOUT_SECONDS",
            "max_output_tokens": "LLM_MAX_OUTPUT_TOKENS", "max_concurrency": "LLM_MAX_CONCURRENCY",
            "input_price_per_million": "LLM_INPUT_PRICE_PER_MILLION",
            "output_price_per_million": "LLM_OUTPUT_PRICE_PER_MILLION",
        }
        return cls(**{field: os.environ[env] for field, env in mapping.items() if os.environ.get(env)})


def create_app(settings=None, provider=None):
    settings = settings or Settings.from_env()
    event_logger = logging.getLogger("intelligence")
    event_logger.setLevel(logging.INFO)
    if not event_logger.handlers:
        event_logger.addHandler(logging.StreamHandler())
    if provider is None:
        provider = DemoProvider() if settings.mode == "demo" else GeminiProvider(
            api_key=settings.gemini_key, model=settings.model,
            timeout_seconds=settings.timeout_seconds, max_output_tokens=settings.max_output_tokens)
    service = DraftService(provider, settings)

    @asynccontextmanager
    async def lifespan(app):
        yield
        close = getattr(provider, "close", None)
        if close:
            close()

    app = FastAPI(title="Marketplace Intelligence", version="1.0.0", lifespan=lifespan)
    app.state.service = service
    security = HTTPBearer(auto_error=False)

    def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
        if (credentials is None or credentials.scheme.lower() != "bearer"
                or not hmac.compare_digest(credentials.credentials.encode(), settings.api_token.encode())):
            raise HTTPException(401, "Credencial inválida.", headers={"WWW-Authenticate": "Bearer"})

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        # Não gera inferências faturáveis; validação de configuração ocorre no startup.
        return {"status": "ready", "mode": settings.mode, "provider_checked": False}

    @app.get("/metrics", dependencies=[Depends(authorize)])
    def metrics():
        return Response(generate_latest(service.registry), headers={"Content-Type": CONTENT_TYPE_LATEST})

    @app.post("/v1/drafts", response_model=DraftResponse, dependencies=[Depends(authorize)])
    def generate(product: ProductInput):
        return service.generate(product)

    @app.exception_handler(ServiceError)
    async def handle_service_error(request, exc):
        headers = {"X-Request-ID": exc.request_id}
        if exc.status_code == 503:
            headers["Retry-After"] = str(int(settings.cooldown_seconds))
        return JSONResponse(status_code=exc.status_code, headers=headers,
                            content={"error": exc.code, "request_id": exc.request_id})

    return app
