"""Ratchet de ``Any`` en producción (``scripts/check_any_count.py``).

Que pasa sobre el árbol de hoy —es lo que hace que CI lo ejecute: no tiene paso
propio en el workflow—, que falla cuando el conteo supera el límite congelado,
y que cuenta usos en el AST y no menciones en comentarios o docstrings.
"""

from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "check_any_count.py"


@pytest.fixture()
def gate():
    spec = importlib.util.spec_from_file_location("check_any_count", _SCRIPT)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["check_any_count"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def test_el_arbol_de_hoy_pasa_el_gate(gate, capsys):
    assert gate.main([]) == 0, capsys.readouterr().err


def test_falla_si_el_conteo_supera_el_limite(gate, monkeypatch, capsys):
    monkeypatch.setattr(gate, "conteo_por_fichero", lambda: Counter({"db/x.py": gate.LIMITE + 1}))

    assert gate.main([]) == 1
    assert "por encima del límite" in capsys.readouterr().err


def test_avisa_para_bajar_el_limite_cuando_baja(gate, monkeypatch, capsys):
    monkeypatch.setattr(gate, "conteo_por_fichero", lambda: Counter({"db/x.py": gate.LIMITE - 5}))

    assert gate.main([]) == 0
    assert f"actualizá LIMITE a {gate.LIMITE - 5}" in capsys.readouterr().out


_FUENTE = '''
"""Docstring que menciona Any: no cuenta."""
import typing
from typing import Any  # el import no es un uso

def f(x: Any) -> dict[str, Any]:  # dos usos; el comentario con Any no cuenta
    y: typing.Any = x  # uno, por atributo
    return {"Any": y}  # la cadena no cuenta
'''


def test_cuenta_usos_y_no_menciones(gate):
    assert gate.usos_de_any(_FUENTE) == 3


def test_vigila_las_capas_de_produccion(gate):
    assert set(gate.PAQUETES) == {
        "config",
        "observability",
        "shared",
        "llm",
        "db",
        "services",
        "scraper",
        "scheduler",
        "api",
        "mcp_server",
    }
