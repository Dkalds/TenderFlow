"""Los índices de ``v142``/``v143`` y las expresiones que consulta la API son las mismas.

Un índice de expresión solo sirve si su expresión coincide con la del ``WHERE``.
Si divergen no falla nada visible: el planificador ignora el índice y la
búsqueda o el filtro de tecnología vuelven al escaneo de ~1,64 M filas. Las dos
revisiones congelan su copia en vez de importarla (ninguna migración de este
linaje importa de ``db/``); este test es el precio de esa decisión.

Si falla la comparación, la corrección **no** es tocar la constante de una
revisión ya escrita —describe el índice que existe o existirá en producción—,
sino escribir una revisión nueva que reconstruya el índice con la expresión
nueva y apuntar aquí a ella, como se hizo con ``v92`` → ``v101``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from db.sql_fragments import fold_expr, tecnologia_tokens_sql

_VERSIONES = Path(__file__).resolve().parents[1] / "db" / "alembic" / "versions"


def _cargar(nombre: str) -> Any:
    """Carga una revisión por ruta: ``db/alembic/versions/`` no es un paquete."""
    spec = importlib.util.spec_from_file_location(nombre, _VERSIONES / f"{nombre}.py")
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


_V142 = _cargar("v142_lic_tecnologia_tokens_gin")
_V143 = _cargar("v143_lic_busqueda_plegada_trgm")


# ── Las expresiones congeladas son las vivas ─────────────────────────────────


def test_el_indice_de_tecnologia_indexa_la_expresion_del_filtro() -> None:
    assert tecnologia_tokens_sql("tecnologia") == _V142._TOKENS_TECNOLOGIA_SQL


@pytest.mark.parametrize(
    ("indice", "columna"),
    [
        ("idx_lic_titulo_plegado_trgm", "titulo"),
        ("idx_lic_descripcion_plegada_trgm", "descripcion"),
        ("idx_lic_organo_plegado_trgm", "organo_contratacion"),
        ("idx_lic_id_externo_plegado_trgm", "id_externo"),
    ],
)
def test_cada_trigram_indexa_la_expresion_plegada_de_su_columna(indice: str, columna: str) -> None:
    assert _V143._INDICES_PLEGADOS[indice] == fold_expr(columna)


def test_hay_un_trigram_por_cada_columna_de_la_busqueda() -> None:
    """Un ``OR`` solo usa índices si **todas** sus ramas lo tienen.

    Si la búsqueda gana una columna, el índice que falte devuelve la consulta
    entera al escaneo secuencial aunque los otros cuatro existan.
    """
    from db.repositories.licitaciones import _COLUMNAS_BUSQUEDA

    columnas_buscadas = {columna.name for columna in _COLUMNAS_BUSQUEDA}
    columnas_indexadas = {
        expresion.split("translate(")[1].split(",")[0]
        for expresion in _V143._INDICES_PLEGADOS.values()
    }
    assert columnas_indexadas == columnas_buscadas


# ── DDL emitido ───────────────────────────────────────────────────────────────


def _sql_emitido(
    modulo: Any,
    funcion: str,
    *,
    dialecto: str = "postgresql",
    indisvalid: bool | None = None,
) -> tuple[list[str], Any]:
    """Ejecuta ``upgrade``/``downgrade`` con ``op`` sustituido y devuelve su DDL.

    ``indisvalid`` es lo que contesta la consulta a ``pg_index``: ``None`` si el
    índice no existe todavía, ``False`` si quedó a medias de un intento fallido.
    """
    emitido: list[str] = []
    with patch.object(modulo, "op") as op_falso:
        op_falso.get_bind.return_value.dialect.name = dialecto
        op_falso.get_bind.return_value.exec_driver_sql.return_value.fetchone.return_value = (
            None if indisvalid is None else (indisvalid,)
        )
        op_falso.execute.side_effect = emitido.append
        getattr(modulo, funcion)()
    return emitido, op_falso


def test_v142_crea_el_gin_sin_bloquear_y_sin_morir_por_timeout() -> None:
    emitido, op_falso = _sql_emitido(_V142, "upgrade")

    assert emitido == [
        "SET statement_timeout = 0",
        "SET lock_timeout = '30s'",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lic_tecnologia_tokens "
        f"ON licitaciones USING gin (({tecnologia_tokens_sql('tecnologia')}))",
        "ANALYZE licitaciones",
    ]
    # `CONCURRENTLY` no puede ir dentro de una transacción.
    op_falso.get_context.return_value.autocommit_block.assert_called_once()


def test_v143_crea_los_cuatro_trigram_y_analiza_una_vez() -> None:
    emitido, op_falso = _sql_emitido(_V143, "upgrade")

    creados = [s for s in emitido if s.startswith("CREATE INDEX CONCURRENTLY IF NOT EXISTS")]
    assert len(creados) == 4
    for nombre, expresion in _V143._INDICES_PLEGADOS.items():
        assert (
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {nombre} "
            f"ON licitaciones USING gin (({expresion}) gin_trgm_ops)"
        ) in creados
    assert emitido[:3] == [
        "SET statement_timeout = 0",
        "SET lock_timeout = '30s'",
        "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    ]
    assert emitido[-1] == "ANALYZE licitaciones"
    op_falso.get_context.return_value.autocommit_block.assert_called_once()


@pytest.mark.parametrize("modulo", [_V142, _V143], ids=["v142", "v143"])
def test_un_indice_invalido_de_un_intento_fallido_se_tira_antes_de_crear(modulo: Any) -> None:
    """El ``IF NOT EXISTS`` de un reintento daría por bueno un índice ``INVALID``."""
    emitido, _ = _sql_emitido(modulo, "upgrade", indisvalid=False)

    tiradas = [s for s in emitido if s.startswith("DROP INDEX CONCURRENTLY IF EXISTS")]
    creadas = [s for s in emitido if s.startswith("CREATE INDEX")]
    assert len(tiradas) == len(creadas) >= 1
    # Cada índice se tira justo antes de su propio CREATE.
    for tirada in tiradas:
        nombre = tirada.rsplit(" ", 1)[1]
        siguiente = emitido[emitido.index(tirada) + 1]
        assert siguiente.startswith(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {nombre} ")


@pytest.mark.parametrize("modulo", [_V142, _V143], ids=["v142", "v143"])
def test_un_indice_valido_no_se_toca(modulo: Any) -> None:
    emitido, _ = _sql_emitido(modulo, "upgrade", indisvalid=True)

    assert not [s for s in emitido if s.startswith("DROP INDEX")]


def test_los_downgrades_tiran_sus_indices_sin_bloquear() -> None:
    emitido_142, _ = _sql_emitido(_V142, "downgrade")
    emitido_143, _ = _sql_emitido(_V143, "downgrade")

    assert emitido_142 == [
        "SET lock_timeout = '30s'",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_lic_tecnologia_tokens",
    ]
    assert emitido_143[0] == "SET lock_timeout = '30s'"
    assert emitido_143[1:] == [
        f"DROP INDEX CONCURRENTLY IF EXISTS {nombre}"
        for nombre in reversed(_V143._INDICES_PLEGADOS)
    ]


@pytest.mark.parametrize("modulo", [_V142, _V143], ids=["v142", "v143"])
@pytest.mark.parametrize("funcion", ["upgrade", "downgrade"])
def test_fuera_de_postgres_no_emite_nada(modulo: Any, funcion: str) -> None:
    emitido, _ = _sql_emitido(modulo, funcion, dialecto="sqlite")

    assert emitido == []


def test_las_dos_revisiones_se_encadenan_sobre_v141() -> None:
    assert _V142.down_revision == "v141_tasas_anulacion_organo"
    assert _V143.down_revision == _V142.revision
