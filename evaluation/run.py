"""python -m evaluation.run [--live] [--output report.json]

Por padrão, mede contratos com fixture local. --live faz chamadas faturáveis.
O relatório não contém dados de clientes, prompts completos ou credenciais.
"""
import argparse
import json
from pathlib import Path
from statistics import mean
import time

from intelligence.api import Settings
from intelligence.contracts import ProductInput
from intelligence.providers import DemoProvider, GeminiProvider
from intelligence.service import DraftService, ServiceError
from intelligence.prompts import PROMPT_VERSION


def evaluate(service, cases):
    results = []
    for case in cases:
        start = time.perf_counter()
        try:
            product = ProductInput.model_validate(case["input"])
            response = service.generate(product)
            text = response.draft.description.casefold()
            checks = {
                "title_length": len(response.draft.title) <= 60,
                "material_grounded": response.draft.material == product.material,
                "human_review": response.draft.requires_review is True,
                "forbidden_claims_absent": not any(term.casefold() in text for term in case.get("forbidden", [])),
            }
            results.append({"id": case["id"], "passed": all(checks.values()), "checks": checks,
                            "latency_ms": round((time.perf_counter() - start) * 1000, 2)})
        except ServiceError as exc:
            results.append({"id": case["id"], "passed": False, "error": exc.code})
    return {
        "mode": service.settings.mode,
        "model": service.settings.model if service.settings.mode == "gemini" else "deterministic-fixture",
        "prompt_version": PROMPT_VERSION,
        "scope": "Small contract/claim regression suite; not an accuracy or production benchmark.",
        "cases": results, "pass_rate": mean(int(row["passed"]) for row in results),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Faz chamadas reais ao Gemini e pode gerar custo.")
    parser.add_argument("--output", default="evaluation-report.json")
    args = parser.parse_args()
    if args.live:
        settings = Settings.from_env().model_copy(update={"mode": "gemini"})
        # Revalidar: model_copy não executa validadores.
        settings = Settings.model_validate(settings.model_dump())
        provider = GeminiProvider(api_key=settings.gemini_key, model=settings.model,
            timeout_seconds=settings.timeout_seconds, max_output_tokens=settings.max_output_tokens)
    else:
        settings = Settings(api_token="offline-evaluation-token")
        provider = DemoProvider()
    try:
        cases = json.loads(Path(__file__).with_name("cases.json").read_text(encoding="utf-8"))
        report = evaluate(DraftService(provider, settings), cases)
        Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"mode": report["mode"], "pass_rate": report["pass_rate"], "output": args.output}))
        return 0 if report["pass_rate"] == 1 else 1
    finally:
        close = getattr(provider, "close", None)
        if close:
            close()


if __name__ == "__main__":
    raise SystemExit(main())
