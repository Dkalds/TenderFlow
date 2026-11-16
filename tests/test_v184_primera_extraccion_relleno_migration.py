"""v184: ``primera_extraccion`` a ``NULL`` se rellena sin re-notificar.

Lo que se fija: el valor es la publicación o la historia, nunca
``fecha_extraccion``, y nunca anterior al relleno de ``v100``; queda por debajo
del cursor del aviso de cuentas comparado como texto, que es como lo compara
``CuentasRepository.publicaciones_nuevas``; la sombra lleva el mismo instante;
no toca las filas que ya tenían valor, una segunda pasada no cambia nada, y la
canónica de un grupo con una gemela rellenada por ``v100`` no cambia.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

from db.database import connect
from db.sql_fragments import orden_canonico_sql

_RUTA = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "alembic"
    / "versions"
    / "v184_primera_extraccion_relleno.py"
)

_CURSOR = "2026-11-14T18:32:51.626036+00:00"
#: El mayor valor que dejó el relleno de `v100` en producción (medido el
#: 2026-11-16) y el suelo de `v184`, que tiene que quedar por encima como texto.
_MAX_V100 = "2026-09-04T08:29:46.152168+00:00"
_SUELO = "2026-09-04T08:30:00.000000+00:00"


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


def test_rellena_entre_el_suelo_de_v100_y_el_cursor(tmp_db) -> None:
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
        _licitacion(c, "publicada-antes-de-v100", pub="2012-03-01")
        _licitacion(c, "publicada-tras-el-cursor", pub="2026-11-15")
        _licitacion(c, "ya-tenia", pub="2026-10-01", primera="2026-10-02T09:00:00+00:00")

        valores = _aplicar(c, veces=2)  # la segunda pasada no cambia nada

    texto = {k: v[0] for k, v in valores.items()}
    assert texto == {
        "pub-antes-que-historia": "2026-10-01T00:00:00.000000+00:00",
        "solo-historia": "2026-10-05T10:00:00.500000+00:00",
        "sin-nada": _SUELO,
        "publicada-antes-de-v100": _SUELO,
        "publicada-tras-el-cursor": "2026-11-14T17:32:51.626036+00:00",
        "ya-tenia": "2026-10-02T09:00:00+00:00",
    }
    # El aviso emite `primera_extraccion > cursor` comparando texto.
    assert all(v is not None and v < _CURSOR for v in texto.values())
    for id_externo, (valor, sombra) in valores.items():
        if id_externo != "ya-tenia":
            assert sombra == datetime.fromisoformat(str(valor))


def test_no_cambia_la_canonica_frente_a_una_gemela_de_v100(tmp_db) -> None:
    # Misma fuente y misma publicación: desempata `primera_extraccion`. Hoy la
    # fila a NULL cae a su `fecha_extraccion` de hoy y pierde; con la
    # publicación como relleno ganaría y el sitemap cambiaría de URL.
    criterio = orden_canonico_sql("l")
    orden = f"SELECT id_externo FROM licitaciones l ORDER BY {criterio} LIMIT 1"  # noqa: S608 -- fragmento constante de db/sql_fragments
    with connect() as c:
        _licitacion(c, "b-rellenada-por-v100", pub="2026-08-20", primera=_MAX_V100)
        _licitacion(c, "a-a-null", pub="2026-08-20")
        antes = c.execute(orden).fetchone()
        _aplicar(c)
        despues = c.execute(orden).fetchone()

    assert antes == despues == ("b-rellenada-por-v100",)


def test_sin_cursor_queda_por_debajo_de_ahora(tmp_db) -> None:
    with connect() as c:
        _licitacion(c, "futura", pub="2099-01-01")
        valor, sombra = _aplicar(c)["futura"]
    tope = datetime.now(UTC) - timedelta(hours=1)

    assert sombra is not None and sombra <= tope
    assert datetime.fromisoformat(str(valor)) == sombra
