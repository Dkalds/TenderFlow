"""Ratchet de capas (``scripts/check_layers.py``).

Las tres propiedades de un ratchet —pasa sobre el árbol de hoy, falla ante una
violación nueva, falla si la lista conserva un fósil— más las dos que son
propias de este: que un import dentro de una función cuente, y que el orden de
capas diga lo que el docstring dice que dice.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "check_layers.py"


def _cargar_modulo():
    spec = importlib.util.spec_from_file_location("check_layers", _SCRIPT)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["check_layers"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture()
def capas():
    return _cargar_modulo()


def test_el_arbol_de_hoy_pasa_el_gate(capas, capsys):
    """El check corrido de verdad: es lo que hace que CI lo ejecute.

    No hay paso propio en el workflow; el gate vive en la suite, así que un
    import invertido nuevo cae aquí, en el mismo job que el resto de tests.
    """
    assert capas.main([]) == 0, capsys.readouterr().err


def test_la_lista_congelada_no_tiene_fosiles(capas):
    assert sorted(capas.CONGELADAS - set(capas.violaciones())) == []


def test_falla_ante_un_import_invertido_nuevo(capas, monkeypatch, capsys):
    nueva = "db/inventado.py -> api.routes.inventada"
    monkeypatch.setattr(capas, "violaciones", lambda: sorted({*capas.CONGELADAS, nueva}))

    assert capas.main([]) == 1
    error = capsys.readouterr().err
    assert nueva in error
    # El mensaje tiene que enseñar el orden: es lo que lee quien lo rompió.
    assert " < ".join(capas.CAPAS) in error


def test_falla_si_la_lista_conserva_un_fosil(capas, monkeypatch, capsys):
    """Una lista que no encoge miente sobre el tamaño de la deuda."""
    quedan = sorted(capas.CONGELADAS)[1:]
    monkeypatch.setattr(capas, "violaciones", lambda: quedan)

    assert capas.main([]) == 1
    assert sorted(capas.CONGELADAS)[0] in capsys.readouterr().err


@pytest.mark.parametrize(
    ("origen", "destino", "esperado"),
    [
        # Hacia abajo y dentro del propio paquete: permitido.
        ("api", "services", False),
        ("services", "db", False),
        ("scraper", "services", False),
        ("db", "db", False),
        # Hacia arriba: violación.
        ("db", "services", True),
        ("shared", "db", True),
        ("services", "scraper", True),
        ("scheduler", "api", True),
        ("config", "shared", True),
        # Prohibida aunque el orden la permita.
        ("api", "scraper", True),
        # Lo que no es un paquete del proyecto no entra en el orden.
        ("api", "fastapi", False),
        ("scripts", "api", False),
    ],
)
def test_el_orden_de_capas(capas, origen, destino, esperado):
    assert capas.es_violacion(origen, destino) is esperado


def test_un_import_dentro_de_una_funcion_cuenta(capas):
    """Es la forma en que se esconde un ciclo, y la que más abunda en la lista."""
    fuente = (
        "from __future__ import annotations\n"
        "from typing import TYPE_CHECKING\n"
        "import os.path\n"
        "from . import hermano\n"
        "if TYPE_CHECKING:\n"
        "    from api.app import app\n"
        "def f():\n"
        "    from services.webhook_retry import decidir\n"
        "    import scheduler.worker\n"
    )

    modulos = capas._modulos_importados(fuente)

    assert {"services.webhook_retry", "scheduler.worker", "api.app"} <= modulos
    # Un import relativo no sale del paquete: no es una arista entre capas.
    assert "hermano" not in modulos


def test_no_cuenta_migraciones_ni_tests_ni_scripts(capas):
    """Las migraciones son históricas; tests y scripts son puntos de entrada."""
    rutas = capas._ficheros()

    assert not [r for r in rutas if r.startswith("db/alembic/versions/")]
    assert not [r for r in rutas if r.startswith(("tests/", "scripts/"))]
    assert any(r.startswith("api/") for r in rutas)


def test_el_worker_no_importa_de_la_api(capas):
    """La violación que motivó el gate, arreglada y no congelada.

    El handler del export importaba ``api.routes.exports`` para maquetar el
    PDF; la función vive ahora en ``services/exports.py``. Ni el scheduler ni
    ninguna capa por debajo de la API la importan.
    """
    hacia_la_api = [v for v in capas.violaciones() if v.split(" -> ")[1].startswith("api")]

    assert hacia_la_api == []


def test_count_imprime_solo_el_numero(capas, capsys):
    assert capas.main(["--count"]) == 0

    assert capsys.readouterr().out.strip().isdigit()
