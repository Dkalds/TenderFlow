"""v158: los eventos PSCP que v153 dejó con la clave vieja vuelven a su licitación.

Dos niveles, como v153. Sin base, la forma de lo que emite la migración. Con
base (``tmp_db``), que reaplicar sus sentencias sobre eventos sembrados con la
clave vieja repunta los que tienen una única licitación candidata, deja
quietos los ambiguos, los de licitaciones que ya no existen y los que ya
estaban bien, y que una segunda pasada no cambia nada.
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
    / "v158_domain_events_pscp_rekey.py"
)

_CLINIC = "38d06b2c-6449-44f1-b47f-60ef10cc0ff6"
_UB = "0b5e3f8a-1c2d-4e5f-8a9b-0c1d2e3f4a5b"
_VILADECANS = "7c1d2e3f-4a5b-4c6d-8e9f-0a1b2c3d4e5f"


def _cargar() -> Any:
    spec = importlib.util.spec_from_file_location("v158_domain_events_pscp_rekey", _RUTA)
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


def test_encadena_con_v157() -> None:
    modulo = _cargar()
    assert modulo.revision == "v158_domain_events_pscp_rekey"
    assert modulo.down_revision == "v157_mv_canonicas_fuente"


def test_fuera_de_postgres_no_emite_nada() -> None:
    assert _sql_emitido("upgrade", dialecto="sqlite") == []
    assert _sql_emitido("downgrade", dialecto="sqlite") == []


def test_el_downgrade_es_un_no_op() -> None:
    assert _sql_emitido("downgrade") == []


def test_no_borra_nada() -> None:
    """Un evento sin licitación es historia de un agregado borrado: se cuenta."""
    assert not any("DELETE" in s.upper() for s in _sql_emitido("upgrade"))


def test_la_clave_nueva_es_la_de_v153() -> None:
    """Si las dos expresiones divergieran, v158 tomaría por vieja una clave que
    v153 dejó como nueva (o al revés)."""
    spec = importlib.util.spec_from_file_location(
        "v153_rekey_pscp_id_externo", _RUTA.with_name("v153_rekey_pscp_id_externo.py")
    )
    assert spec is not None and spec.loader is not None
    v153 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(v153)
    assert _cargar()._CLAVE_NUEVA == v153._CLAVE_NUEVA


def test_el_codigo_empieza_tras_el_uuid() -> None:
    nuevo = f"pscp:{_CLINIC}:2026/18"
    assert nuevo[_cargar()._INICIO_CODIGO - 1 :] == "2026/18"


# ---------------------------------------------------------------------------
# Con base
# ---------------------------------------------------------------------------


def _licitacion(c: Any, id_externo: str, *, fuente: str = "pscp") -> None:
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, fuente, "
        " fecha_extraccion, fecha_publicacion) "
        "VALUES (%s, %s, 'Organo', %s, '2026-09-27T02:31:41+00:00', '2026-07-13')",
        (id_externo, f"Contrato {id_externo}", fuente),
    )


def _evento(c: Any, aggregate_id: str, *, aggregate_type: str = "licitacion") -> int:
    fila = c.execute(
        "INSERT INTO domain_events (event_type, aggregate_id, aggregate_type, payload_json, "
        " created_at, dispatched_at) "
        "VALUES ('licitacion.tecnologia_pliego', %s, %s, '{\"tecnologia\": \"SAP\"}', "
        " '2026-10-01T00:00:00+00:00', '2026-10-01T00:05:00+00:00') RETURNING id",
        (aggregate_id, aggregate_type),
    ).fetchone()
    return int(fila[0])


def _sembrar(c: Any) -> dict[str, int]:
    """Lo de prod en pequeño: un evento de cada caso."""
    _licitacion(c, f"pscp:{_CLINIC}:Obert")
    # `2026/18` lo llevan dos órganos: es la colisión que separó v153.
    _licitacion(c, f"pscp:{_UB}:2026/18")
    _licitacion(c, f"pscp:{_VILADECANS}:2026/18")
    # Fila PSCP sin ficha: v153 le dejó la clave vieja.
    _licitacion(c, "pscp:SIN-FICHA")
    _licitacion(c, "2026/18", fuente="placsp")
    return {
        "repuntable": _evento(c, "pscp:Obert"),
        "repuntable_bis": _evento(c, "pscp:Obert"),
        "ambiguo": _evento(c, "pscp:2026/18"),
        "sin_licitacion": _evento(c, "pscp:BORRADA"),
        "ya_nuevo": _evento(c, f"pscp:{_UB}:2026/18"),
        "sin_ficha": _evento(c, "pscp:SIN-FICHA"),
        "placsp": _evento(c, "2026/18"),
        "placsp_huerfano": _evento(c, "Obert"),
        "otro_agregado": _evento(c, "pscp:Obert", aggregate_type="pursuit"),
    }


def _ids(c: Any) -> dict[int, tuple[str, str, str]]:
    return {
        int(f[0]): (str(f[1]), str(f[2]), str(f[3]))
        for f in c.execute(
            "SELECT id, aggregate_id, aggregate_type, payload_json FROM domain_events"
        ).fetchall()
    }


def test_repunta_solo_los_huerfanos_con_una_unica_candidata(tmp_db: Any) -> None:
    with connect() as c:
        eventos = _sembrar(c)
        antes = _ids(c)
    with connect() as c:
        for sentencia in _cargar().sentencias_upgrade():
            c.execute(sentencia)
        despues = _ids(c)

    obert = f"pscp:{_CLINIC}:Obert"
    esperado = dict(antes)
    for clave in ("repuntable", "repuntable_bis"):
        _, tipo, payload = antes[eventos[clave]]
        esperado[eventos[clave]] = (obert, tipo, payload)
    assert despues == esperado
    # Lo que no se pudo repuntar sigue ahí, con su id de siempre.
    assert despues[eventos["ambiguo"]][0] == "pscp:2026/18"
    assert despues[eventos["sin_licitacion"]][0] == "pscp:BORRADA"
    assert despues[eventos["otro_agregado"]][0] == "pscp:Obert"


def test_reaplicarla_no_cambia_nada(tmp_db: Any) -> None:
    with connect() as c:
        _sembrar(c)
    with connect() as c:
        for sentencia in _cargar().sentencias_upgrade():
            c.execute(sentencia)
        primera = _ids(c)
    with connect() as c:
        for sentencia in _cargar().sentencias_upgrade():
            c.execute(sentencia)
        assert _ids(c) == primera


def test_la_historia_del_agregado_aparece_en_la_licitacion(tmp_db: Any) -> None:
    """Para lo que se arregla: `get_events` desde la ficha nueva los encuentra."""
    from db.events import get_events

    with connect() as c:
        _sembrar(c)
    obert = f"pscp:{_CLINIC}:Obert"
    assert get_events("licitacion", obert) == []
    with connect() as c:
        for sentencia in _cargar().sentencias_upgrade():
            c.execute(sentencia)
    assert len(get_events("licitacion", obert)) == 2
