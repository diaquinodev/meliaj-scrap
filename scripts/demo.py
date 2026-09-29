"""Uma execução inicia API e dashboard com o mesmo token efêmero, em modo demo."""

import argparse
from contextlib import ExitStack
import json
import os
import secrets
import time
import webbrowser

from .runtime import check_port, demo_api, managed_process, wait_ready
from .smoke import check_service


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-port", type=int, default=8001)
    parser.add_argument("--ui-port", type=int, default=8501)
    parser.add_argument("--open", action="store_true", help="Abre o dashboard no navegador padrão.")
    parser.add_argument("--check", action="store_true", help="Valida API e health do dashboard; depois encerra ambos.")
    args = parser.parse_args()
    if not all(1 <= port <= 65535 for port in (args.api_port, args.ui_port)):
        parser.error("Portas precisam estar entre 1 e 65535.")
    if args.api_port == args.ui_port:
        parser.error("API e dashboard precisam de portas diferentes.")
    token = secrets.token_urlsafe(32)
    api_url = f"http://127.0.0.1:{args.api_port}"
    ui_url = f"http://127.0.0.1:{args.ui_port}"
    try:
        check_port(args.ui_port)
        with ExitStack() as stack:
            api = stack.enter_context(demo_api(args.api_port, token))
            report = check_service(api_url, token)
            env = os.environ.copy()
            env.update(SERVICE_API_TOKEN=token, SERVICE_API_URL=api_url, RADAR_DEMO_AUTOLOAD="1")
            ui = stack.enter_context(managed_process([
                "-m", "streamlit", "run", "app/radar_app.py",
                "--server.address", "127.0.0.1", "--server.port", str(args.ui_port),
                "--server.headless", "true", "--browser.gatherUsageStats", "false",
                "--global.developmentMode", "false",
            ], env))
            wait_ready(ui, ui_url + "/_stcore/health")
            report["dashboard_health"] = "passed"
            if args.check:
                print(json.dumps(report), flush=True)
                return 0
            print(f"\nDemonstração pronta: {ui_url}\nAPI: {api_url}/docs\nModo demo; sem inferência paga. Ctrl+C encerra os dois serviços.", flush=True)
            if args.open:
                webbrowser.open(ui_url)
            while api.poll() is None and ui.poll() is None:
                time.sleep(0.5)
            raise RuntimeError("Um serviço encerrou. A demonstração foi finalizada.")
    except KeyboardInterrupt:
        print("\nDemonstração encerrada.")
        return 0
    except (RuntimeError, OSError) as exc:
        print(f"Não foi possível executar a demonstração: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
