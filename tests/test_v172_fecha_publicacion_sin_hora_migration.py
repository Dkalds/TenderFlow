"""v172: ``fecha_publicacion`` con hora pasa a ``YYYY-MM-DD``, y su sombra con ella.

Sin base, la forma de lo que emite la migración. Con base (``tmp_db``), que
la normalización se queda con la fecha del propio texto, recalcula
``fecha_publicacion_ts`` y no toca lo que ya era una fecha sola (un CHECK de
la tabla ya impide guardar algo que no sea ISO).
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from db.database import connect

_RUTA = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "alembic"
    / "versions"
    / "v172_fecha_publicacion_sin_hora.py"
)


def _cargar() -> Any:
    spec = importlib.util.spec_from_file_location("v172_fecha_publicacion_sin_hora", _RUTA)
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


def test_encadena_con_v171() -> None:
    modulo = _cargar()
    assert modulo.revision == "v172_fecha_publicacion_sin_hora"
    assert modulo.down_revision == "v171_access_grants_revoked_by"


def test_fuera_de_postgres_no_emite_nada() -> None:
    assert _sql_emitido("upgrade", dialecto="sqlite") == []


def test_la_bajada_no_emite_nada() -> None:
    assert _sql_emitido("downgrade") == []


def test_normaliza_solo_las_fechas_con_hora_y_su_sombra(tmp_db: Any) -> None:
    filas_semilla = {
        "V172-HORA": "2026-04-16T19:30:59.268+02:00",
        "V172-NOCHE": "2026-04-16T23:30:00+00:00",
        "V172-FECHA": "2026-04-16",
    }
    with connect() as c:
        for id_externo, fecha in filas_semilla.items():
            c.execute(
                "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion, fecha_publicacion) "
                "VALUES (%s, 't', '2026-09-04T00:00:00+00:00', %s)",
                (id_externo, fecha),
            )
        for sentencia in _sql_emitido("upgrade"):
            c.execute(sentencia)
        filas = {
            str(f[0]): (f[1], f[2])
            for f in c.execute(
                "SELECT id_externo, fecha_publicacion, fecha_publicacion_ts FROM licitaciones "
                "WHERE id_externo LIKE 'V172-%'"
            ).fetchall()
        }

    medianoche = datetime(2026, 4, 16, tzinfo=UTC)
    # La fecha del propio texto, no la UTC: 23:30Z sigue siendo el día 16.
    assert filas["V172-HORA"] == ("2026-04-16", medianoche)
    assert filas["V172-NOCHE"] == ("2026-04-16", medianoche)
    assert filas["V172-FECHA"][0] == "2026-04-16"
