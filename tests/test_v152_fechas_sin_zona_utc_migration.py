"""v152: las fechas en texto sin zona (las de SQLite) se reescriben en ISO como UTC.

Sin base, la forma de lo que emite la migración: que cubre las mismas columnas
que v151 y que el trigger de tecnología se reactiva. Con base (``tmp_db``), que
la normalización convierte solo el formato sin zona, leyéndolo como UTC, y deja
como estaba lo que ya es ISO, lo que lleva offset y lo que no es una fecha.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import patch

from db.database import connect

_VERSIONES = Path(__file__).resolve().parents[1] / "db" / "alembic" / "versions"


def _cargar(nombre: str = "v152_fechas_sin_zona_utc") -> Any:
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


def test_encadena_con_v151() -> None:
    modulo = _cargar()
    assert modulo.revision == "v152_fechas_sin_zona_utc"
    assert modulo.down_revision == "v151_fechas_texto_iso"


def test_fuera_de_postgres_no_emite_nada() -> None:
    assert _sql_emitido("upgrade", dialecto="sqlite") == []
    assert _sql_emitido("downgrade", dialecto="sqlite") == []


def test_cubre_las_mismas_columnas_que_v151() -> None:
    """Copiadas a mano (una migración no importa otra): si divergen, una
    columna que v151 normalizó se quedaría con las filas sin zona."""
    v151 = _cargar("v151_fechas_texto_iso")
    assert sorted(_cargar()._COLUMNAS) == sorted([*v151._COLUMNAS, *v151._SOLO_DATOS])


def test_el_trigger_de_tecnologia_se_reactiva_despues_de_normalizar() -> None:
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


def test_no_toca_el_esquema() -> None:
    """Solo datos: el DEFAULT ya lo corrigió v151."""
    emitido = _sql_emitido("upgrade")
    assert not [s for s in emitido if "SET DEFAULT" in s]


# ---------------------------------------------------------------------------
# Con base
# ---------------------------------------------------------------------------


def test_la_normalizacion_lee_como_utc_solo_lo_que_no_tiene_zona(tmp_db) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion) "
            "VALUES ('V152-DAT', 't', '2026-05-21T00:00:00+00:00')"
        )
        for uri, creado in (
            ("https://placsp.test/sqlite.pdf", "2026-05-21 15:02:22"),
            ("https://placsp.test/sqlite-frac.pdf", "2026-05-21 15:02:22.5"),
            ("https://placsp.test/iso.pdf", "2026-05-21T15:02:22+00:00"),
            ("https://placsp.test/con-offset.pdf", "2026-05-21 17:02:22+02"),
            ("https://placsp.test/solo-fecha.pdf", "2026-05-21"),
            ("https://placsp.test/raro.pdf", "ayer por la tarde"),
        ):
            c.execute(
                "INSERT INTO documentos (licitacion_id, tipo, uri, created_at) "
                "VALUES ('V152-DAT', 'technical', %s, %s)",
                (uri, creado),
            )
        for sentencia in _sql_emitido("upgrade"):
            c.execute(sentencia)
        filas = dict(
            c.execute(
                "SELECT uri, created_at FROM documentos WHERE licitacion_id = 'V152-DAT'"
            ).fetchall()
        )
    assert filas == {
        "https://placsp.test/sqlite.pdf": "2026-05-21T15:02:22.000000+00:00",
        "https://placsp.test/sqlite-frac.pdf": "2026-05-21T15:02:22.500000+00:00",
        "https://placsp.test/iso.pdf": "2026-05-21T15:02:22+00:00",
        # Con offset es asunto de v151, no de esta revisión.
        "https://placsp.test/con-offset.pdf": "2026-05-21 17:02:22+02",
        "https://placsp.test/solo-fecha.pdf": "2026-05-21",
        "https://placsp.test/raro.pdf": "ayer por la tarde",
    }
