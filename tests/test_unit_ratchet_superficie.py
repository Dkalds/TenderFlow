"""Ratchet de superficie de la API (``scripts/check_api_surface.py``).

Una operación nueva tiene que llegar con su motivo; la línea base solo encoge.
El check real corre en un proceso aparte con el mismo entorno que el paso de
``docs/STATUS.md`` en CI, porque la lista de rutas depende de ``ENV`` y de
``APP_PROFILE`` y la app de este proceso ya se importó con los de la suite.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "check_api_surface.py"


def _cargar_modulo():
    spec = importlib.util.spec_from_file_location("check_api_surface", _SCRIPT)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["check_api_surface"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture()
def superficie():
    return _cargar_modulo()


@pytest.fixture()
def simulada(superficie, monkeypatch):
    """Una API de dos operaciones heredadas, para mover una pieza por test."""
    base = {"GET /a", "POST /a"}
    monkeypatch.setattr(superficie, "operaciones", lambda: sorted(base))
    monkeypatch.setattr(superficie, "leer_base", lambda: set(base))
    monkeypatch.setattr(superficie, "NUEVAS", {})
    return superficie


def test_la_api_de_hoy_pasa_el_gate():
    """El check corrido de verdad contra la app: es lo que CI ejecuta."""
    entorno = {**os.environ, "ENV": "dev", "APP_PROFILE": "api", "PYTHONUTF8": "1"}
    proceso = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        cwd=_ROOT,
        env=entorno,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=300,
    )

    assert proceso.returncode == 0, proceso.stderr[-4000:]
    assert "Ratchet de superficie OK" in proceso.stdout


def test_la_linea_base_esta_ordenada_y_sin_repetidos(superficie):
    """Ordenada, dos ramas que borran líneas distintas fusionan sin conflicto."""
    lineas = [
        s
        for linea in superficie._BASE.read_text(encoding="utf-8").splitlines()
        if (s := linea.strip()) and not s.startswith("#")
    ]

    assert lineas == sorted(set(lineas))
    assert all(linea.split(" ", 1)[1].startswith("/") for linea in lineas)


def test_pasa_cuando_la_app_es_exactamente_la_base(simulada, capsys):
    assert simulada.main([]) == 0
    assert "2 operaciones" in capsys.readouterr().out


def test_falla_ante_una_operacion_nueva_sin_motivo(simulada, monkeypatch, capsys):
    monkeypatch.setattr(simulada, "operaciones", lambda: ["GET /a", "GET /nueva", "POST /a"])

    assert simulada.main([]) == 1
    error = capsys.readouterr().err
    assert "GET /nueva" in error
    # Quien lo rompe tiene que leer la regla, no solo el nombre del gate.
    assert "AGENTS.md §0" in error


def test_una_operacion_nueva_con_motivo_pasa(simulada, monkeypatch, capsys):
    monkeypatch.setattr(simulada, "operaciones", lambda: ["GET /a", "GET /nueva", "POST /a"])
    monkeypatch.setattr(
        simulada,
        "NUEVAS",
        {"GET /nueva": "GET /a devuelve el recurso entero y aquí hace falta solo su resumen."},
    )

    assert simulada.main([]) == 0
    assert "1 añadidas con motivo" in capsys.readouterr().out


def test_un_motivo_de_compromiso_no_vale(simulada, monkeypatch, capsys):
    monkeypatch.setattr(simulada, "operaciones", lambda: ["GET /a", "GET /nueva", "POST /a"])
    monkeypatch.setattr(simulada, "NUEVAS", {"GET /nueva": "hace falta"})

    assert simulada.main([]) == 1
    assert "GET /nueva" in capsys.readouterr().err


def test_falla_si_la_base_conserva_una_operacion_retirada(simulada, monkeypatch, capsys):
    """Retirar un endpoint obliga a borrar su línea: así encoge la base."""
    monkeypatch.setattr(simulada, "operaciones", lambda: ["GET /a"])

    assert simulada.main([]) == 1
    assert "POST /a" in capsys.readouterr().err


def test_falla_si_nuevas_conserva_una_operacion_retirada(simulada, monkeypatch, capsys):
    monkeypatch.setattr(
        simulada,
        "NUEVAS",
        {"GET /ya-no": "GET /a no paginaba y esta vista necesitaba cursor; ya se retiró."},
    )

    assert simulada.main([]) == 1
    assert "GET /ya-no" in capsys.readouterr().err


def test_una_operacion_heredada_no_se_justifica_dos_veces(simulada, monkeypatch, capsys):
    monkeypatch.setattr(
        simulada,
        "NUEVAS",
        {"GET /a": "Ya estaba en la línea base, así que esta entrada sobra por completo."},
    )

    assert simulada.main([]) == 1
    assert "ya están en la línea base" in capsys.readouterr().err


def test_las_nuevas_reales_llevan_todas_motivo(superficie):
    """La lista de verdad, no la simulada: ningún motivo de compromiso en el repo."""
    cortos = [
        op
        for op, motivo in superficie.NUEVAS.items()
        if len(motivo.strip()) < superficie.MOTIVO_MINIMO
    ]

    assert cortos == []
