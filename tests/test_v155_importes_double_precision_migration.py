"""v155: los importes pasan de ``real`` a ``double precision`` rehaciendo la vista.

Sin base, la forma de lo que emite: que encadena detrás de ``v154``, que cada
tabla se reescribe con un solo ``ALTER`` (una reescritura por tabla, no una por
columna), que la vista se tira antes y se rehace después, y que su cuerpo es
literalmente el de ``v102``.

Con base, el caso de producción: una base recién migrada crea las columnas ya en
``double precision`` (``baseline002``), así que el test las baja a ``real`` con
el propio downgrade —que es lo que hay en producción— y comprueba que la subida
las deja en float8, que la vista vuelve con su índice único y que un importe con
céntimos hace el viaje de ida y vuelta exacto.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from db.database import connect

_VERSIONES = Path(__file__).resolve().parents[1] / "db" / "alembic" / "versions"

_COLUMNAS = {
    ("licitaciones", "importe"),
    ("licitaciones", "duracion_valor"),
    ("adjudicaciones", "importe_adjudicado"),
    ("adjudicaciones", "importe_pagable"),
    ("adjudicaciones", "oferta_minima"),
    ("adjudicaciones", "oferta_maxima"),
}


def _cargar(nombre: str = "v155_importes_double_precision") -> Any:
    spec = importlib.util.spec_from_file_location(nombre, _VERSIONES / f"{nombre}.py")
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


# ---------------------------------------------------------------------------
# Forma, sin base
# ---------------------------------------------------------------------------


def test_encadena_con_v154() -> None:
    modulo = _cargar()
    assert modulo.revision == "v155_importes_double_precision"
    assert modulo.down_revision == "v154_importe_tipo_galicia_desconocido"


def test_cubre_las_seis_columnas() -> None:
    modulo = _cargar()
    assert {(t, c) for t, cols in modulo.COLUMNAS.items() for c in cols} == _COLUMNAS


def test_la_vista_se_rehace_con_el_cuerpo_de_v102() -> None:
    """Copiado a mano (una migración no importa otra): si divergiera, esta
    revisión cambiaría en silencio qué publica la superficie pública."""
    assert _cargar()._CUERPO == _cargar("v102_mv_canonicas_clave_inmutable")._CUERPO


def test_una_reescritura_por_tabla_entre_tirar_y_rehacer_la_vista() -> None:
    emitido = _sql_emitido("upgrade")
    alters = [s for s in emitido if s.startswith("ALTER TABLE")]
    assert [s.split()[2] for s in alters] == ["licitaciones", "adjudicaciones"]
    assert all("TYPE double precision" in s for s in alters)

    tirar = emitido.index("DROP MATERIALIZED VIEW IF EXISTS licitaciones_canonicas")
    crear = next(i for i, s in enumerate(emitido) if s.startswith("CREATE MATERIALIZED VIEW"))
    assert tirar < emitido.index(alters[0]) < emitido.index(alters[-1]) < crear
    assert any(
        s.startswith("CREATE UNIQUE INDEX uq_licitaciones_canonicas_id_externo") for s in emitido
    )


def test_el_downgrade_vuelve_a_real() -> None:
    alters = [s for s in _sql_emitido("downgrade") if s.startswith("ALTER TABLE")]
    assert len(alters) == 2
    assert all("TYPE real" in s and "double" not in s for s in alters)


def test_no_deja_timeouts_de_sesion_puestos() -> None:
    """Alembic aplica varias revisiones en una transacción: lo que se ponga aquí
    lo heredarían las siguientes."""
    emitido = _sql_emitido("upgrade")
    assert emitido[-2:] == ["RESET lock_timeout", "RESET statement_timeout"]


def test_fuera_de_postgres_no_emite_nada() -> None:
    assert _sql_emitido("upgrade", dialecto="sqlite") == []
    assert _sql_emitido("downgrade", dialecto="sqlite") == []


# ---------------------------------------------------------------------------
# Con base
# ---------------------------------------------------------------------------


def _tipos(c: Any) -> dict[tuple[str, str], str]:
    filas = c.execute(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = current_schema() "
        "AND table_name IN ('licitaciones', 'adjudicaciones')"
    ).fetchall()
    return {(str(t), str(col)): str(tipo) for t, col, tipo in filas if (t, col) in _COLUMNAS}


@pytest.mark.schema_propio
def test_de_real_a_double_con_la_vista_viva(tmp_db) -> None:
    importe = 11_782_154.55
    with connect() as c:
        for sentencia in _sql_emitido("downgrade"):
            c.execute(sentencia)
        assert set(_tipos(c).values()) == {"real"}
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, importe, fecha_extraccion) "
            "VALUES ('V155-1', 'Contrato de prueba con importe de once millones', %s, "
            "'2026-10-23T00:00:00+00:00')",
            (importe,),
        )
        # float4 se come los céntimos: el estado de producción.
        guardado = c.execute(
            "SELECT importe FROM licitaciones WHERE id_externo = 'V155-1'"
        ).fetchone()
        assert guardado is not None and float(guardado[0]) != importe

        for sentencia in _sql_emitido("upgrade"):
            c.execute(sentencia)
        assert set(_tipos(c).values()) == {"double precision"}

        c.execute("UPDATE licitaciones SET importe = %s WHERE id_externo = 'V155-1'", (importe,))
        c.execute(
            "INSERT INTO adjudicaciones (licitacion_id, nombre, importe_adjudicado, "
            "fecha_extraccion) VALUES ('V155-1', 'Empresa', %s, '2026-10-23T00:00:00+00:00')",
            (importe,),
        )
        lic = c.execute("SELECT importe FROM licitaciones WHERE id_externo = 'V155-1'").fetchone()
        adj = c.execute(
            "SELECT importe_adjudicado FROM adjudicaciones WHERE licitacion_id = 'V155-1'"
        ).fetchone()
        assert lic is not None and float(lic[0]) == importe
        assert adj is not None and float(adj[0]) == importe

        indice = c.execute(
            "SELECT 1 FROM pg_indexes WHERE schemaname = current_schema() "
            "AND indexname = 'uq_licitaciones_canonicas_id_externo'"
        ).fetchone()
        assert indice is not None, "sin el índice único, REFRESH CONCURRENTLY falla"
        # La vista vuelve poblada y con el contrato publicable dentro.
        en_vista = c.execute(
            "SELECT count(*) FROM licitaciones_canonicas WHERE id_externo = 'V155-1'"
        ).fetchone()
        assert en_vista is not None and en_vista[0] == 1
