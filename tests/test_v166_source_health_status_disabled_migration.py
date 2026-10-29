"""v166: ``source_ingestion_health.status`` admite ``'disabled'`` (#578).

Sin ella, ``record_source_disabled`` moría con ``CheckViolation`` y la fuente
apagada a propósito salía en el healthcheck como ``sin_registro``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import patch

_VERSIONES = Path(__file__).resolve().parents[1] / "db" / "alembic" / "versions"


def _cargar() -> Any:
    nombre = "v166_source_health_status_disabled"
    spec = importlib.util.spec_from_file_location(nombre, _VERSIONES / f"{nombre}.py")
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _sql_emitido(funcion: str) -> list[str]:
    modulo = _cargar()
    emitido: list[str] = []
    with patch.object(modulo, "op") as op_falso:
        op_falso.execute.side_effect = emitido.append
        getattr(modulo, funcion)()
    return emitido


def test_encadena_con_v165() -> None:
    modulo = _cargar()
    assert modulo.revision == "v166_source_health_status_disabled"
    assert modulo.down_revision == "v165_user_id_fase3_tanda3"


def test_admite_el_estado_que_escriben_los_conectores_y_lee_el_healthcheck() -> None:
    from scheduler.healthcheck import ESTADO_FUENTE_APAGADA
    from scraper.connectors.base import SOURCE_STATUS_DISABLED

    estados = _cargar().ESTADOS
    assert SOURCE_STATUS_DISABLED in estados
    assert ESTADO_FUENTE_APAGADA in estados
    upgrade = _sql_emitido("upgrade")[-1]
    assert "status IN ('running','success','partial','failed','disabled')" in upgrade


def test_el_downgrade_borra_las_filas_disabled_antes_de_estrechar() -> None:
    emitido = _sql_emitido("downgrade")
    assert emitido[0] == "DELETE FROM source_ingestion_health WHERE status = 'disabled'"
    assert "status IN ('running','success','partial','failed'))" in emitido[-1]


def test_una_fuente_apagada_queda_escrita_y_el_healthcheck_la_ve_apagada(tmp_db) -> None:
    from db.repositories.source_health import SourceHealthRepository
    from scheduler.healthcheck import comprobar_frescura_fuentes
    from scraper.connectors.base import record_source_disabled

    record_source_disabled("placsp_agregadas", motivo="PLACSP_AGREGADAS_ATOM_URL vacía")

    filas = {fila["source"]: fila for fila in SourceHealthRepository().list_health()}
    assert filas["placsp_agregadas"]["status"] == "disabled"
    frescura = comprobar_frescura_fuentes()
    assert "placsp_agregadas" in frescura["apagadas"]
    assert "placsp_agregadas" not in frescura["sin_registro"]
