"""v190: vista materializada ``empresas_agregados``.

Lo que se fija: encadena con ``v189``; el cuerpo congelado cuenta lo mismo que
el agregado vivo de ``db/repositories/empresas.py``; la vista tiene el índice
único que exige ``REFRESH ... CONCURRENTLY``; y el refresco del repositorio
deja una fila por empresa del maestro, con ceros para la que no tiene
adjudicaciones.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from db.database import connect

_RUTA = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "alembic"
    / "versions"
    / "v190_mv_empresas_agregados.py"
)


def _cargar() -> Any:
    spec = importlib.util.spec_from_file_location("v190_mv_empresas_agregados", _RUTA)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_encadena_con_v189() -> None:
    modulo = _cargar()
    assert modulo.revision == "v190_mv_empresas_agregados"
    assert modulo.down_revision == "v189_jobs_terminados_indice"


def test_el_cuerpo_cuenta_lo_mismo_que_el_listado() -> None:
    from db.repositories import empresas

    cuerpo = _cargar().CUERPO
    assert "COUNT(a.id) AS n_adjudicaciones" in cuerpo
    assert "COALESCE(SUM(a.importe_adjudicado), 0) AS importe_total" in cuerpo
    assert "COUNT(a.id) AS n_adjudicaciones" in empresas._LISTA_SELECT
    assert "COALESCE(SUM(a.importe_adjudicado), 0) AS importe_total" in empresas._LISTA_SELECT
    assert _cargar().VISTA == empresas.VISTA_AGREGADOS


@pytest.mark.usefixtures("tmp_db")
def test_la_vista_tiene_indice_unico_y_el_refresco_cubre_el_maestro() -> None:
    from db.repositories.empresas import refrescar_agregados_empresas

    with connect() as c:
        unico = c.execute(
            "SELECT 1 FROM pg_indexes WHERE indexname = 'uq_empresas_agregados_empresa'"
        ).fetchone()
        c.execute("INSERT INTO empresas (nombre_canonico) VALUES ('Sin Contratos SL')")

    assert unico is not None
    assert refrescar_agregados_empresas() == 1
    # El segundo refresco ya va CONCURRENTLY sobre una vista poblada.
    assert refrescar_agregados_empresas() == 1
    with connect() as c:
        fila = c.execute(
            "SELECT n_adjudicaciones, importe_total FROM empresas_agregados"
        ).fetchone()
    assert tuple(fila) == (0, 0)
