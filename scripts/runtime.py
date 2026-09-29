"""Gerencia somente os processos filhos criados pela demonstração."""

from contextlib import contextmanager
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
LOCAL_HTTP = build_opener(ProxyHandler({}))


def available_port():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return server.getsockname()[1]


def check_port(port):
    try:
        with socket.socket() as server:
            server.bind(("127.0.0.1", port))
    except OSError as exc:
        raise RuntimeError(f"Porta {port} ocupada. Escolha outra porta para a demonstração.") from exc


def wait_ready(process, url, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"O processo encerrou com código {process.returncode} durante a inicialização. Consulte a saída do servidor.")
        try:
            with LOCAL_HTTP.open(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (URLError, TimeoutError, OSError):
            pass
        time.sleep(0.2)
    raise RuntimeError(f"Serviço não ficou pronto em {timeout}s: {url}")


@contextmanager
def managed_process(arguments, env):
    process = subprocess.Popen(
        [sys.executable, *arguments], cwd=ROOT, env=env,
        stdout=sys.stdout, stderr=sys.stderr,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        yield process
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@contextmanager
def demo_api(port, token):
    check_port(port)
    env = os.environ.copy()
    env.update(LLM_MODE="demo", SERVICE_API_TOKEN=token, PYTHONUNBUFFERED="1")
    with managed_process([
        "-m", "uvicorn", "intelligence.api:create_app", "--factory",
        "--host", "127.0.0.1", "--port", str(port), "--no-access-log",
    ], env) as process:
        wait_ready(process, f"http://127.0.0.1:{port}/health/ready")
        yield process
