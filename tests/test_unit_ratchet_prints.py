"""Ratchet de ``print()`` (``scripts/check_prints.py``).

Que pasa sobre el árbol de hoy —es lo que hace que CI lo ejecute: no tiene paso
propio en el workflow—, que falla ante un ``print()`` nuevo y ante un fósil en
``CONGELADAS``, y que la frontera es el bloque ``if __name__ == "__main__"``,
no la función ``main()`` que se llama desde él.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "check_prints.py"


@pytest.fixture()
def gate():
    spec = importlib.util.spec_from_file_location("check_prints", _SCRIPT)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["check_prints"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def test_el_arbol_de_hoy_pasa_el_gate(gate, capsys):
    assert gate.main([]) == 0, capsys.readouterr().err


def test_falla_ante_un_print_nuevo(gate, monkeypatch, capsys):
    monkeypatch.setattr(gate, "encontrar", lambda: ["scraper/connectors/inventado.py:12"])

    assert gate.main([]) == 1
    assert "scraper/connectors/inventado.py:12" in capsys.readouterr().err


def test_falla_si_la_lista_conserva_un_fosil(gate, monkeypatch, capsys):
    monkeypatch.setattr(gate, "CONGELADAS", frozenset({"services/ya_no_existe.py:3"}))

    assert gate.main([]) == 1
    assert "services/ya_no_existe.py:3" in capsys.readouterr().err


_FUENTE = """
import sys

def main():
    print("cuenta: main() es importable")

def ayudante():
    return print

if __name__ == "__main__":
    print("no cuenta: cuerpo del programa")
    def interna():
        print("no cuenta: definida dentro del bloque")
else:
    print("cuenta: el else es código de importación")

if "__main__" == __name__:
    print("no cuenta: el orden invertido también es el bloque")

sys.stdout.write("esto no es print(): lo vigila la revisión, no el gate")
"""


def test_la_frontera_es_el_bloque_main_y_no_la_funcion_main(gate):
    encontrados = gate.prints_de(_FUENTE, "x.py")

    lineas = _FUENTE.splitlines()
    textos = [lineas[int(e.split(":")[1]) - 1].strip() for e in encontrados]
    assert textos == [
        'print("cuenta: main() es importable")',
        'print("cuenta: el else es código de importación")',
    ]


def test_vigila_los_tres_paquetes_del_criterio(gate):
    assert set(gate.PAQUETES) == {"scraper", "services", "scheduler"}
    assert not gate.CONGELADAS


def test_las_anotaciones_de_actions_salen_por_su_modulo() -> None:
    """``scheduler/run_update.py`` las emitía con ``print``; la sintaxis vive en un sitio."""
    import io

    from observability.acciones_github import anotar

    salida = io.StringIO()
    anotar("error", "post-ingestion step failed", "dlq_retry", salida=salida)
    anotar("warning", "a: b, c", "línea 1\nlínea 2 al 100%", salida=salida)

    assert salida.getvalue().splitlines() == [
        "::error title=post-ingestion step failed::dlq_retry",
        "::warning title=a%3A b%2C c::línea 1%0Alínea 2 al 100%25",
    ]
