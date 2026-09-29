"""Teste HTTP contra API real em modo demo; não chama provedores pagos."""

import argparse
import json
import os
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request

from .runtime import LOCAL_HTTP


def check_service(base_url, token):
    parts = urlsplit(base_url)
    if parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("O smoke test aceita apenas uma API HTTP em loopback.")
    if not token:
        raise ValueError("SERVICE_API_TOKEN não foi informado.")
    base_url = base_url.rstrip("/")

    def call(path, payload=None, authorized=True):
        headers = {"Content-Type": "application/json"}
        if authorized:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(base_url + path, headers=headers,
                          data=None if payload is None else json.dumps(payload).encode())
        try:
            with LOCAL_HTTP.open(request, timeout=10) as response:
                return response.status, response.read().decode()
        except HTTPError as exc:
            return exc.code, exc.read().decode()

    def require(condition, name):
        if not condition:
            raise RuntimeError(f"Smoke test falhou: {name}")

    require(call("/health/live", authorized=False)[0] == 200, "liveness")
    status, content = call("/health/ready", authorized=False)
    require(status == 200 and json.loads(content).get("mode") == "demo", "API precisa estar em modo demo")
    payload = {"name": "Body feminino", "details": "Cor preta. Manga longa.", "material": None}
    require(call("/v1/drafts", payload, authorized=False)[0] == 401, "autenticação")
    require(call("/v1/drafts", {"name": "x"})[0] == 422, "entrada inválida")
    status, content = call("/v1/drafts", payload)
    require(status == 200, "geração")
    result = json.loads(content)
    require(result["mode"] == "demo" and result["draft"]["requires_review"] is True, "contrato de revisão")
    require(result["draft"]["material"] is None, "material não inventado")
    require(result["estimated_cost_usd"] is None, "custo desconhecido explícito")
    require(call("/metrics", authorized=False)[0] == 401, "métricas protegidas")
    status, metrics = call("/metrics")
    require(status == 200 and 'llm_requests_total{outcome="success"}' in metrics, "métricas exportadas")
    return {"status": "passed", "mode": "demo", "checks": 10, "request_id": result["request_id"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    args = parser.parse_args()
    print(json.dumps(check_service(args.base_url, os.getenv("SERVICE_API_TOKEN", ""))))


if __name__ == "__main__":
    main()
