"""v151: las fechas en texto con ``DEFAULT now()`` escriben y guardan ISO con ``T``.

Dos niveles. Sin base, la forma de lo que emite la migración. Con base
(``tmp_db``), que el esquema migrado ya no deja ninguna columna ``text`` con
``DEFAULT now()`` —una nueva reabriría el fallo de «desde tu última visita»— y
que la normalización de datos convierte el formato de ``now()::text`` sin tocar
lo que ya era ISO ni un valor que no sea una fecha.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

from db.database import connect

_RUTA = (
    Path(__file__).resolve().parents[1] / "db" / "alembic" / "versions" / "v151_fechas_texto_iso.py"
)

#: Lo que escribe ``db.connection.now_utc_iso()``.
_ISO_APP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$")


def _cargar() -> Any:
    spec = importlib.util.spec_from_file_location("v151_fechas_texto_iso", _RUTA)
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


def test_encadena_con_v150() -> None:
    modulo = _cargar()
    assert modulo.revision == "v151_fechas_texto_iso"
    assert modulo.down_revision == "v150_mcp_oauth"


def test_fuera_de_postgres_no_emite_nada() -> None:
    assert _sql_emitido("upgrade", dialecto="sqlite") == []
    assert _sql_emitido("downgrade", dialecto="sqlite") == []


def test_el_trigger_de_tecnologia_se_reactiva_despues_de_normalizar() -> None:
    """Desactivado sólo alrededor de los ``UPDATE`` de su tabla: si se quedara
    apagado, ``licitaciones.ml_tecnologias`` dejaría de derivarse para siempre."""
    emitido = _sql_emitido("upgrade")
    apagar = emitido.index(
        "ALTER TABLE licitacion_tecnologia_score DISABLE TRIGGER trg_lts_derivar_ml"
    )
    encender = emitido.index(
        "ALTER TABLE licitacion_tecnologia_score ENABLE TRIGGER trg_lts_derivar_ml"
    )
    entre = emitido[apagar + 1 : encender]
    assert entre, "no hay nada entre apagar y encender el trigger"
    assert all(s.startswith("UPDATE licitacion_tecnologia_score ") for s in entre)


# ---------------------------------------------------------------------------
# Con base
# ---------------------------------------------------------------------------


def test_ninguna_columna_de_texto_queda_con_default_now(tmp_db) -> None:
    """El ratchet: una migración futura que declare ``text DEFAULT now()``
    vuelve a escribir fechas con espacio, y las comparaciones de texto contra
    un corte ISO vuelven a dejar fuera lo del mismo día."""
    with connect() as c:
        filas = c.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND data_type = 'text' "
            "  AND column_default ~* '^\\(?now\\(\\)\\)?$' "
            "ORDER BY 1, 2"
        ).fetchall()
    assert [tuple(f) for f in filas] == []


def test_un_insert_que_omite_la_fecha_la_escribe_como_la_aplicacion(tmp_db) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion) "
            "VALUES ('V151-DEF', 't', '2026-09-16T00:00:00+00:00')"
        )
        c.execute(
            "INSERT INTO documentos (licitacion_id, tipo, uri) "
            "VALUES ('V151-DEF', 'technical', 'https://placsp.test/v151.pdf')"
        )
        creado, actualizado = c.execute(
            "SELECT created_at, updated_at FROM documentos WHERE licitacion_id = 'V151-DEF'"
        ).fetchone()
    assert _ISO_APP.match(creado), creado
    assert _ISO_APP.match(actualizado), actualizado


def test_la_normalizacion_convierte_solo_el_formato_de_now(tmp_db) -> None:
    """Se reaplica la parte de datos de la migración sobre filas sembradas con
    el formato antiguo: en UTC, con ``T`` y offset completo. Lo que ya es ISO
    y lo que no es una fecha se quedan como estaban."""
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion) "
            "VALUES ('V151-DAT', 't', '2026-09-16T00:00:00+00:00')"
        )
        for uri, creado in (
            ("https://placsp.test/utc.pdf", "2026-09-16 15:00:00.123456+00"),
            ("https://placsp.test/madrid.pdf", "2026-09-16 17:00:00+02"),
            ("https://placsp.test/iso.pdf", "2026-09-16T15:00:00+00:00"),
            ("https://placsp.test/raro.pdf", "ayer por la tarde"),
        ):
            c.execute(
                "INSERT INTO documentos (licitacion_id, tipo, uri, created_at) "
                "VALUES ('V151-DAT', 'technical', %s, %s)",
                (uri, creado),
            )
        for sentencia in _sql_emitido("upgrade"):
            c.execute(sentencia)
        filas = dict(
            c.execute(
                "SELECT uri, created_at FROM documentos WHERE licitacion_id = 'V151-DAT'"
            ).fetchall()
        )
    assert filas == {
        "https://placsp.test/utc.pdf": "2026-09-16T15:00:00.123456+00:00",
        "https://placsp.test/madrid.pdf": "2026-09-16T15:00:00.000000+00:00",
        "https://placsp.test/iso.pdf": "2026-09-16T15:00:00+00:00",
        "https://placsp.test/raro.pdf": "ayer por la tarde",
    }
