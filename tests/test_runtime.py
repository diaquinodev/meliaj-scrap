import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys

import pytest
from streamlit.testing.v1 import AppTest

from scripts.runtime import available_port, demo_api
from scripts.smoke import check_service


@pytest.fixture(scope="module")
def real_api():
    port, token = available_port(), secrets.token_urlsafe(32)
    with demo_api(port, token):
        yield f"http://127.0.0.1:{port}", token
    # O processo filho deve liberar a porta ao sair do contexto.
    with socket.socket() as connection:
        assert connection.connect_ex(("127.0.0.1", port)) != 0


def test_real_http_contract(real_api):
    url, token = real_api
    report = check_service(url, token)
    assert report["status"] == "passed"
    assert report["checks"] == 10


def test_dashboard_generates_draft_over_real_http(real_api, monkeypatch):
    url, token = real_api
    monkeypatch.setenv("SERVICE_API_URL", url)
    monkeypatch.setenv("SERVICE_API_TOKEN", token)
    monkeypatch.setenv("RADAR_DEMO_AUTOLOAD", "1")
    at = AppTest.from_file(str(Path(__file__).parents[1] / "app" / "radar_app.py"), default_timeout=45).run()
    assert not at.exception
    assert len(at.dataframe[0].value) == 5
    next(button for button in at.button if button.label == "Gerar rascunho para revisão").click().run()
    assert not at.exception
    assert not at.error
    assert at.session_state["draft"]["mode"] == "demo"
    assert at.session_state["draft"]["draft"]["requires_review"] is True


def test_demo_command_starts_and_stops_both_services():
    api_port, ui_port = available_port(), available_port()
    while api_port == ui_port:
        ui_port = available_port()
    result = subprocess.run([
        sys.executable, "-m", "scripts.demo", "--check",
        "--api-port", str(api_port), "--ui-port", str(ui_port),
    ], cwd=Path(__file__).parents[1], capture_output=True, text=True, timeout=75,
       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert result.returncode == 0, result.stdout + result.stderr
    reports = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{"status"')]
    assert reports[0]["dashboard_health"] == "passed"
    for port in (api_port, ui_port):
        with socket.socket() as connection:
            assert connection.connect_ex(("127.0.0.1", port)) != 0
