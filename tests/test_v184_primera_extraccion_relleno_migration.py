"""v184: ``primera_extraccion`` a ``NULL`` se rellena sin re-notificar.

Lo que se fija: el valor es lo más temprano que se sabe de la fila
(publicación, historia, fecha de ``v100``), nunca ``fecha_extraccion``; queda
por debajo del cursor del aviso de cuentas comparado como texto, que es como
lo compara ``CuentasRepository.publicaciones_nuevas``; la sombra lleva el mismo
instante; no toca las filas que ya tenían valor, y una segunda pasada no cambia
nada.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

from db.database import connect

_RUTA = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "alembic"
    / "versions"
    / "v184_primera_extraccion_relleno.py"
)

_CURSOR = "2026-11-14T18:32:51.626036+00:00"


def _cargar() -> Any:
    spec = importlib.util.spec_from_file_location("v184_primera_extraccion_relleno", _RUTA)
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


def _licitacion(c: Any, id_externo: str, *, pub: str | None, primera: str | None = None) -> None:
    # `fecha_extraccion` de hoy, como la deja cada reingesta: no debe usarse.
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_publicacion, "
        "primera_extraccion, fecha_extraccion) VALUES (%s, 't', 'placsp', %s, %s, %s)",
        (id_externo, pub, primera, datetime.now(UTC).isoformat()),
    )


def _historia(c: Any, id_externo: str, captured_at: str) -> None:
    c.execute(
        "INSERT INTO licitaciones_history (id_externo, captured_at, snapshot_json, "
        "changed_fields) VALUES (%s, %s, '{}', '[]')",
        (id_externo, captured_at),
    )


def _aplicar(c: Any, veces: int = 1) -> dict[str, tuple[str | None, datetime | None]]:
    for _ in range(veces):
        for sentencia in _sql_emitido("upgrade"):
            c.execute(sentencia)
    filas = c.execute(
        "SELECT id_externo, primera_extraccion, primera_extraccion_ts FROM licitaciones"
    ).fetchall()
    return {f[0]: (f[1], f[2]) for f in filas}


def test_encadena_con_v183() -> None:
    modulo = _cargar()
    assert modulo.revision == "v184_primera_extraccion_relleno"
    assert modulo.down_revision == "v183_api_keys_activa_con_dueno"


def test_el_downgrade_no_hace_nada() -> None:
    assert _sql_emitido("downgrade") == []


def test_fuera_de_postgres_no_emite_nada() -> None:
    assert _sql_emitido("upgrade", dialecto="sqlite") == []


def test_rellena_con_lo_mas_temprano_y_bajo_el_cursor(tmp_db) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO ingestion_cursors (source, last_seen_updated, updated_at) "
            "VALUES ('outbox_cuentas_publicaciones', %s, %s)",
            (_CURSOR, _CURSOR),
        )
        _licitacion(c, "pub-antes-que-historia", pub="2026-10-01")
        _historia(c, "pub-antes-que-historia", "2026-10-05T10:00:00+00:00")
        _licitacion(c, "solo-historia", pub=None)
        _historia(c, "solo-historia", "2026-10-20T08:00:00+00:00")
        _historia(c, "solo-historia", "2026-10-05T10:00:00.5+00:00")
        _licitacion(c, "sin-nada", pub=None)
        _licitacion(c, "publicada-tras-el-cursor", pub="2026-11-15")
        _licitacion(c, "ya-tenia", pub="2026-10-01", primera="2026-10-02T09:00:00+00:00")

        valores = _aplicar(c, veces=2)  # la segunda pasada no cambia nada

    texto = {k: v[0] for k, v in valores.items()}
    assert texto == {
        "pub-antes-que-historia": "2026-10-01T00:00:00.000000+00:00",
        "solo-historia": "2026-10-05T10:00:00.500000+00:00",
        "sin-nada": "2026-09-03T00:00:00.000000+00:00",
        "publicada-tras-el-cursor": "2026-11-14T17:32:51.626036+00:00",
        "ya-tenia": "2026-10-02T09:00:00+00:00",
    }
    # El aviso emite `primera_extraccion > cursor` comparando texto.
    assert all(v is not None and v < _CURSOR for v in texto.values())
    for id_externo, (valor, sombra) in valores.items():
        if id_externo != "ya-tenia":
            assert sombra == datetime.fromisoformat(str(valor))


def test_sin_cursor_queda_por_debajo_de_ahora(tmp_db) -> None:
    with connect() as c:
        _licitacion(c, "futura", pub="2099-01-01")
        valor, sombra = _aplicar(c)["futura"]
    tope = datetime.now(UTC) - timedelta(hours=1)

    assert sombra is not None and sombra <= tope
    assert datetime.fromisoformat(str(valor)) == sombra
