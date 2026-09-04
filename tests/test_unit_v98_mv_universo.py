"""El DDL que emite ``v98``: construir al lado, permutar, y volver atrás igual.

Un PR con una migración necesita un test que fije lo que emite —el job de
migraciones de CI la ejecuta pero no la mide— y aquí además se fija la forma:
que la vista nueva se construya **antes** de tirar la vieja, porque la vía
obvia (``DROP`` y ``CREATE``) deja la superficie pública sin vista durante la
construcción. Mismo harness que ``tests/test_clave_canonica_index.py``: se
sustituye ``op`` entero y se recoge el SQL.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import patch

#: El universo tal y como ``v98`` lo congeló. **No** se importa
#: ``universo_tecnologico_sql``: ese fragmento sigue vivo y ya cambió una vez
#: (``v99`` le añadió ``ml_tecnologias``), mientras que el cuerpo de una revisión
#: aplicada describe la vista que existe en producción y es append-only. Comparar
#: la revisión vieja contra el fragmento de hoy hacía fallar este test cada vez
#: que el universo evoluciona, que es justo lo que la revisión NO debe seguir.
_UNIVERSO_V98 = (
    "(COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed' "
    "OR l.analysis_universe IN ('galicia_rss_recent_technology_observed', "
    "'euskadi_rss_recent_technology_observed') "
    "OR (l.tecnologia IS NOT NULL AND l.tecnologia <> ''))"
)

_RUTA = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "alembic"
    / "versions"
    / "v98_mv_canonicas_universo_tecnologico.py"
)


def _cargar() -> Any:
    spec = importlib.util.spec_from_file_location("v98_mv_canonicas_universo_tecnologico", _RUTA)
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


def test_el_cuerpo_nuevo_solo_anade_el_universo_al_de_v94() -> None:
    """La única diferencia con v94 es el tercer término del WHERE."""
    modulo = _cargar()
    universo = _UNIVERSO_V98

    assert universo in modulo._CUERPO
    assert universo not in modulo._CUERPO_ANTERIOR
    assert modulo._CUERPO.replace(f" AND {universo}", "") == modulo._CUERPO_ANTERIOR


def test_upgrade_construye_al_lado_y_permuta_sin_dejar_hueco() -> None:
    emitido = _sql_emitido("upgrade")
    modulo = _cargar()

    assert emitido[0] == "SET statement_timeout = 0"
    crear = next(s for s in emitido if s.startswith("CREATE MATERIALIZED VIEW"))
    assert crear.startswith(f"CREATE MATERIALIZED VIEW {modulo.VISTA_NUEVA} AS ")
    assert modulo._CUERPO in crear

    # El orden es lo que evita el hueco: la vieja se tira después de que la
    # nueva exista con su índice único, y el RENAME va justo detrás.
    i_crear = emitido.index(crear)
    i_unico = next(i for i, s in enumerate(emitido) if s.startswith("CREATE UNIQUE INDEX"))
    i_drop = emitido.index(f"DROP MATERIALIZED VIEW IF EXISTS {modulo.VISTA}")
    i_rename = emitido.index(
        f"ALTER MATERIALIZED VIEW {modulo.VISTA_NUEVA} RENAME TO {modulo.VISTA}"
    )
    assert i_crear < i_unico < i_drop < i_rename


def test_los_indices_conservan_los_nombres_de_v94() -> None:
    """``refrescar_vista_canonicas`` y el planificador dan por hechos estos nombres."""
    emitido = _sql_emitido("upgrade")
    texto = "\n".join(emitido)

    assert "RENAME TO uq_licitaciones_canonicas_id_externo" in texto
    for indice in (
        "idx_licitaciones_canonicas_fecha_pub",
        "idx_licitaciones_canonicas_ccaa",
        "idx_licitaciones_canonicas_cpv",
    ):
        assert f"CREATE INDEX IF NOT EXISTS {indice}" in texto
    assert emitido[-1] == "ANALYZE licitaciones_canonicas"


def test_downgrade_vuelve_al_cuerpo_de_v94_con_la_misma_permuta() -> None:
    emitido = _sql_emitido("downgrade")
    modulo = _cargar()

    crear = next(s for s in emitido if s.startswith("CREATE MATERIALIZED VIEW"))
    assert modulo._CUERPO_ANTERIOR in crear
    assert modulo._CUERPO not in crear
    assert f"ALTER MATERIALIZED VIEW {modulo.VISTA_NUEVA} RENAME TO {modulo.VISTA}" in emitido


def test_fuera_de_postgres_no_emite_nada() -> None:
    assert _sql_emitido("upgrade", dialecto="sqlite") == []
    assert _sql_emitido("downgrade", dialecto="sqlite") == []
