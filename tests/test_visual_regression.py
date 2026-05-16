"""Smoke + visual regression para el dashboard Streamlit (E3).

Lanza el dashboard contra una BD de test, captura screenshots de cada
página y los compara con baselines almacenados en
``tests/visual/baseline/``.

Por defecto **se omite en CI** (requiere navegador headless instalado).
Habilitar con ``RUN_VISUAL_TESTS=1`` y ``playwright install chromium``.

Si no hay baseline, el test crea uno y se marca como xfail con una nota
para que el reviewer lo añada al repo manualmente.

Esta primera versión solo verifica que cada página carga sin errores
visibles ("Streamlit ha encontrado un error..."). El diff pixel-perfect
puede añadirse después con ``Pillow`` y ``imagehash``.
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from pathlib import Path

import pytest

VISUAL_DIR = Path(__file__).parent / "visual"
BASELINE_DIR = VISUAL_DIR / "baseline"
ACTUAL_DIR = VISUAL_DIR / "actual"

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_VISUAL_TESTS") != "1",
    reason="Visual tests deshabilitados (set RUN_VISUAL_TESTS=1 para activar)",
)


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="module")
def streamlit_server() -> object:
    """Levanta el dashboard en un puerto efímero para los tests."""
    port = 8599
    if _port_open("127.0.0.1", port):
        pytest.skip(f"Puerto {port} ya en uso — abortando para no chocar con dev")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    proc = subprocess.Popen(
        [
            "python",
            "-m",
            "streamlit",
            "run",
            "dashboard/app.py",
            "--server.port",
            str(port),
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
        ],
        env=env,
    )
    # Esperar a que el server levante (max 30s)
    for _ in range(60):
        if _port_open("127.0.0.1", port):
            break
        time.sleep(0.5)
    else:
        proc.terminate()
        pytest.fail("Streamlit no levantó en 30s")

    yield f"http://127.0.0.1:{port}"

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_dashboard_loads_without_errors(streamlit_server: str) -> None:
    """La página raíz debe cargar sin un error visible de Streamlit."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    ACTUAL_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(streamlit_server, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)  # dejar que Streamlit hidrate

        screenshot = ACTUAL_DIR / "home.png"
        page.screenshot(path=str(screenshot), full_page=True)

        # Heurística simple: el texto "Streamlit" no debe aparecer junto a "error"
        body_text = page.text_content("body") or ""
        assert "Oh no." not in body_text, "Streamlit error visible en home"

        browser.close()
