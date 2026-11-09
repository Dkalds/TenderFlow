"""v177: fuera de los RSS autonómicos lo que solo entró por «licitación electrónica».

Lo que se fija: que borra solo las filas de los RSS cuya única keyword es esa y
cuyo título no la nombra, que respeta las que tienen trabajo de usuario, que la
fila mixta medida queda como la escribiría el conector de hoy, y que una
segunda pasada no cambia nada.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import patch

from db.database import connect

_RUTA = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "alembic"
    / "versions"
    / "v177_rss_autonomico_sin_tramitacion.py"
)

_TRAMITACION = "licitación electrónica"


def _cargar() -> Any:
    spec = importlib.util.spec_from_file_location("v177_rss_autonomico_sin_tramitacion", _RUTA)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _sql_emitido(funcion: str, *, dialecto: str = "postgresql") -> list[str]:
    modulo = _cargar()
    emitido: list[str] = []
    with patch.object(modulo, "op") as op_falso:
        op_falso.get_bind.return_value.dialect.name = dialecto
        op_falso.execute.side_effect = emitido.append
        getattr(modulo, funcion)()
    return emitido


def test_encadena_con_v176() -> None:
    modulo = _cargar()
    assert modulo.revision == "v177_rss_autonomico_sin_tramitacion"
    assert modulo.down_revision == "v176_consultas_recientes"


def test_el_downgrade_no_hace_nada() -> None:
    assert _sql_emitido("downgrade") == []


def test_fuera_de_postgres_no_emite_nada() -> None:
    assert _sql_emitido("upgrade", dialecto="sqlite") == []


def _fila(c: Any, id_externo: str, fuente: str, titulo: str, tecnologia: str, kws: str) -> None:
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, fuente, tecnologia, raw_keywords, "
        "fecha_extraccion) VALUES (%s, %s, %s, %s, %s, '2026-11-05T00:00:00+00:00')",
        (id_externo, titulo, fuente, tecnologia, kws),
    )


def _notificar(c: Any, id_externo: str) -> None:
    c.execute(
        "INSERT INTO user_notifications (user_key, created_at, type, title, licitacion_id) "
        "VALUES ('alice', '2026-11-05T00:00:00+00:00', 'rule_match', 't', %s)",
        (id_externo,),
    )


def _seguir(c: Any, id_externo: str, kind: str) -> None:
    c.execute(
        "INSERT INTO follows (user_key, target_type, target_id, kind) "
        "VALUES ('alice', 'licitacion', %s, %s)",
        (id_externo, kind),
    )


def _migrar_dos_veces(c: Any) -> None:
    for _ in range(2):  # idempotente
        for sentencia in _sql_emitido("upgrade"):
            c.execute(sentencia)


def _ids(c: Any, tabla: str, columna: str) -> set[str]:
    sql = f"SELECT {columna} FROM {tabla}"  # noqa: S608 - tabla y columna son literales del test
    return {str(f[0]) for f in c.execute(sql).fetchall()}


def test_borra_lo_que_solo_entro_por_la_prosa_y_lo_que_cuelga_de_ello(tmp_db) -> None:
    with connect() as c:
        _fila(c, "galicia_rss:1", "galicia_rss", "Dos vehículos", "ADMIN_ELECTRONICA", _TRAMITACION)
        _fila(
            c,
            "euskadi_rss:2",
            "euskadi_rss",
            "Altzarien hornidura",
            "ADMIN_ELECTRONICA",
            _TRAMITACION,
        )
        _fila(c, "placsp:5", "placsp", "Suministro de lácteos", "ADMIN_ELECTRONICA", _TRAMITACION)
        c.execute(
            "INSERT INTO licitaciones_history (id_externo, captured_at, source, changed_fields, "
            "snapshot_json) VALUES ('galicia_rss:1', '2026-11-06T00:00:00+00:00', 'test', "
            "'[\"estado\"]', '{}')"
        )
        _notificar(c, "galicia_rss:1")
        _seguir(c, "galicia_rss:1", "descartar")
        _notificar(c, "placsp:5")
        _migrar_dos_veces(c)

        assert _ids(c, "licitaciones", "id_externo") == {"placsp:5"}
        assert _ids(c, "licitaciones_history", "id_externo") == set()
        assert _ids(c, "user_notifications", "licitacion_id") == {"placsp:5"}
        assert _ids(c, "follows", "target_id") == set()


def test_conserva_lo_que_algo_mas_sostiene(tmp_db) -> None:
    with connect() as c:
        _fila(
            c,
            "galicia_rss:3",
            "galicia_rss",
            "Plataforma de LICITACIÓN ELECTRÓNICA",
            "ADMIN_ELECTRONICA",
            _TRAMITACION,
        )
        _fila(c, "galicia_rss:4", "galicia_rss", "Mantemento SAP", "SAP", "sap")
        for n in ("6", "7", "8", "9"):
            _fila(
                c, f"galicia_rss:{n}", "galicia_rss", "Ecógrafo", "ADMIN_ELECTRONICA", _TRAMITACION
            )
        c.execute(
            "INSERT INTO watchlist_items (user_key, user_id, id_externo, organization_id) "
            "VALUES ('alice', NULL, 'galicia_rss:6', NULL)"
        )
        _seguir(c, "galicia_rss:7", "seguir")
        c.execute(
            "INSERT INTO licitacion_tecnologia_score (licitacion_id, tecnologia, probabilidad, "
            "threshold_aplicado, computed_at) VALUES ('galicia_rss:8', 'PUESTO_TRABAJO', 0.9, 0.5, "
            "'2026-11-06T00:00:00+00:00')"
        )
        c.execute(
            "INSERT INTO ml_feedback (expediente, relevante, tecnologia, source, created_at) "
            "VALUES ('galicia_rss:9', 0, NULL, 'revision_ti', CURRENT_TIMESTAMP)"
        )
        _migrar_dos_veces(c)

        assert _ids(c, "licitaciones", "id_externo") == {f"galicia_rss:{n}" for n in "346789"}


def test_la_fila_mixta_queda_como_la_escribiria_el_conector(tmp_db) -> None:
    with connect() as c:
        _fila(
            c,
            "galicia_rss:829225",
            "galicia_rss",
            "Servicios de desarrollo de un sistema de gestión",
            "ADMIN_ELECTRONICA,DESARROLLO",
            f"{_TRAMITACION},servicios de desarrollo",
        )
        _migrar_dos_veces(c)
        fila = c.execute("SELECT tecnologia, raw_keywords FROM licitaciones").fetchone()

    assert tuple(fila) == ("DESARROLLO", "servicios de desarrollo")
