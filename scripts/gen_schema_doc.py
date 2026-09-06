#!/usr/bin/env python3
"""Genera ``docs/database-schema.md`` a partir del esquema real de Postgres.

Misma regla que ``scripts/gen_status.py``: **si un hecho se puede calcular, no
se escribe a mano**. Este documento se mantuvo a mano durante meses y acabó
describiendo un motor retirado y veinte versiones de un sistema de migraciones
que ya no corre, mientras Alembic iba por la centésima revisión. Un documento
de esquema que miente es peor que no tenerlo: quien lo lee toma decisiones de
persistencia sobre columnas que no existen.

El generador aplica ``alembic upgrade head`` sobre ``TEST_DATABASE_URL`` y lee
el catálogo de la base resultante (``information_schema``, ``pg_constraint``,
``pg_indexes``, ``pg_matviews``). No hay una segunda fuente de verdad: lo que
aparece aquí es lo que Alembic crea, tabla por tabla.

Sobre ADR-022 («todo el SQL vive en ``db/``»): las consultas de este fichero no
son persistencia de dominio. Leen el *catálogo* de una base efímera —ni una
fila de negocio— y no pasan por el pool de la aplicación, igual que
``tests/conftest.py`` levanta el esquema con ``pg_dump``. Ponerlas en ``db/``
metería introspección de documentación en la capa de datos del producto.

Uso::

    python scripts/gen_schema_doc.py            # escribe docs/database-schema.md
    python scripts/gen_schema_doc.py --check    # falla si el fichero está desfasado

Códigos de salida (distinguibles a propósito: el job de CI que solo tiene
lint no debe confundir «documento desfasado» con «aquí no hay Postgres»)::

    0  el documento está al día, o se acaba de escribir
    1  el documento commiteado no coincide con el esquema
    2  no hay con qué generarlo: falta TEST_DATABASE_URL, o Alembic/psycopg fallan
"""

from __future__ import annotations

import difflib
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_OUT = _ROOT / "docs" / "database-schema.md"

_MARKER = "<!-- generado por scripts/gen_schema_doc.py — no editar a mano -->"

_SIN_BD = 2
"""Código de salida cuando no hay base de datos con la que generar nada."""

# `alembic_version` es el libro de contabilidad de Alembic, no esquema del
# producto: listarla solo añadiría ruido que cambia en cada migración.
_TABLAS_EXCLUIDAS = frozenset({"alembic_version"})


# ───────────────────────────── modelo de datos ─────────────────────────────


@dataclass(frozen=True)
class Columna:
    """Una fila de ``information_schema.columns`` reducida a lo que se publica."""

    tabla: str
    nombre: str
    tipo: str
    nullable: bool


@dataclass(frozen=True)
class Restriccion:
    """Clave primaria o única, tal como la imprime ``pg_get_constraintdef``."""

    tabla: str
    definicion: str


@dataclass(frozen=True)
class Indice:
    """Índice explícito. Los que respaldan una constraint no llegan aquí."""

    relacion: str
    nombre: str
    unico: bool


@dataclass(frozen=True)
class Esquema:
    """Catálogo completo leído de una base ya migrada a ``head``."""

    revision: str
    columnas: tuple[Columna, ...] = ()
    restricciones: tuple[Restriccion, ...] = ()
    indices: tuple[Indice, ...] = ()
    matviews: tuple[str, ...] = ()
    vistas: tuple[str, ...] = ()


# ─────────────────────────── agrupación por familia ───────────────────────────

# Orden de presentación. Una tabla cae en la primera familia cuyo nombre exacto
# o prefijo case; los prefijos existen para que una tabla nueva aterrice sola en
# la familia correcta en vez de irse a «Otras» y desfasar el documento.
_FAMILIAS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "Licitaciones y fuente",
        (
            "licitaciones",
            "lotes",
            "adjudicaciones",
            "contrato_eventos",
            "resoluciones_recurso",
            "ingestion_cursors",
            "extracciones",
            "extraction_runs",
            "failed_extractions",
            "source_ingestion_health",
        ),
        ("licitaciones_",),
    ),
    (
        "Documentos y pliegos",
        ("tender_fact_sheets",),
        ("documento", "pliego"),
    ),
    (
        "Empresas y mercado",
        ("grupos_empresariales", "ute_miembros", "mat_clusters"),
        ("empresa",),
    ),
    (
        "Organizaciones y oportunidades",
        (),
        ("organization", "pursuit"),
    ),
    (
        "Identidad, acceso y auditoría",
        (
            "users",
            "sessions",
            "solicitudes_acceso",
            "password_reset_tokens",
            "idempotency_keys",
            "rate_limits",
            "csp_violations",
        ),
        ("api_key", "access_", "audit_", "totp_", "oauth_"),
    ),
    (
        "Seguimiento y notificaciones",
        (
            "saved_filters",
            "user_profiles",
            "radar_dismissals",
            "notification_reads",
            "user_notifications",
            "pending_digests",
        ),
        ("watchlist_", "webhook"),
    ),
    (
        "ML y predicciones",
        ("feature_store",),
        ("ml_", "model_", "licitacion_tecnologia", "predicciones_"),
    ),
    (
        "Operación y observabilidad",
        ("domain_events", "ops_events", "job_locks", "kpi_snapshots", "feature_flags", "jobs"),
        (),
    ),
)

_OTRAS = "Otras"


def familia(tabla: str) -> str:
    """Familia a la que pertenece ``tabla``.

    Los nombres exactos ganan a los prefijos dentro de la misma familia, pero el
    recorrido es por orden de familia: ``licitacion_tecnologia_score`` es de ML
    aunque empiece por ``licitacion`` porque «Licitaciones y fuente» solo declara
    el prefijo ``licitaciones_`` (con ese ``es`` que las separa).
    """
    for nombre, exactos, prefijos in _FAMILIAS:
        if tabla in exactos or (bool(prefijos) and tabla.startswith(prefijos)):
            return nombre
    return _OTRAS


def agrupar(tablas: Iterable[str]) -> list[tuple[str, list[str]]]:
    """Tablas por familia, en orden de familia y alfabético dentro de cada una."""
    por_familia: dict[str, list[str]] = {}
    for tabla in tablas:
        por_familia.setdefault(familia(tabla), []).append(tabla)
    orden = [nombre for nombre, _, _ in _FAMILIAS] + [_OTRAS]
    return [(nombre, sorted(por_familia[nombre])) for nombre in orden if nombre in por_familia]


def _orden_restriccion(definicion: str) -> tuple[int, str]:
    """La clave primaria primero; las únicas después, alfabéticas."""
    return (0 if definicion.startswith("PRIMARY KEY") else 1, definicion)


# ───────────────────────────────── render ─────────────────────────────────


@dataclass
class _Agregado:
    """Contadores por familia para la tabla de resumen."""

    tablas: int = 0
    columnas: int = 0
    indices: int = 0


def render(esquema: Esquema, hoy: str | None = None) -> str:
    """Markdown completo del documento. Función pura: solo depende de ``esquema``."""
    fecha = hoy or datetime.now(UTC).date().isoformat()

    columnas_por_tabla: dict[str, list[Columna]] = {}
    for col in esquema.columnas:
        if col.tabla in _TABLAS_EXCLUIDAS:
            continue
        columnas_por_tabla.setdefault(col.tabla, []).append(col)

    restricciones_por_tabla: dict[str, list[str]] = {}
    for res in esquema.restricciones:
        if res.tabla in _TABLAS_EXCLUIDAS:
            continue
        restricciones_por_tabla.setdefault(res.tabla, []).append(res.definicion)

    indices_por_relacion: dict[str, list[Indice]] = {}
    for idx in esquema.indices:
        if idx.relacion in _TABLAS_EXCLUIDAS:
            continue
        indices_por_relacion.setdefault(idx.relacion, []).append(idx)

    grupos = agrupar(columnas_por_tabla)

    lines: list[str] = [
        "---",
        "tags: [database, schema, generado]",
        "---",
        "",
        "# Esquema de base de datos",
        "",
        _MARKER,
        "",
        f"Generado: {fecha}",
        "",
        f"Revisión Alembic aplicada: `{esquema.revision}`.",
        "",
        "Catálogo de una base Postgres recién migrada con `alembic upgrade head`. Se listan",
        "las tablas de `public` agrupadas por familia, con sus columnas",
        "(`information_schema.columns`, en orden de `ordinal_position`), sus claves primarias",
        "y únicas (`pg_constraint`) y sus índices explícitos (`pg_indexes`, sin los que",
        "respaldan una constraint porque ya se ven arriba). Quedan fuera a propósito la tabla",
        "de control de Alembic, las claves ajenas y los `CHECK` —que se entienden mejor en la",
        "migración que los declara— y, por supuesto, cualquier dato.",
        "",
        (
            "> Nota histórica: hasta 2026-09 este fichero se mantenía a mano y describía el "
            "esquema SQLite, su tabla virtual FTS5 y las versiones v1-v20 del sistema casero "
            "`db/migrations.py`, retirados por ADR-016 y ADR-021."
        ),
        "",
        "## Resumen",
        "",
        "| Familia | Tablas | Columnas | Índices |",
        "|---|---:|---:|---:|",
    ]

    total = _Agregado()
    for nombre, tablas in grupos:
        agg = _Agregado()
        for tabla in tablas:
            agg.tablas += 1
            agg.columnas += len(columnas_por_tabla[tabla])
            agg.indices += len(indices_por_relacion.get(tabla, []))
        total.tablas += agg.tablas
        total.columnas += agg.columnas
        total.indices += agg.indices
        lines.append(f"| {nombre} | {agg.tablas} | {agg.columnas} | {agg.indices} |")
    lines.append(f"| **Total** | **{total.tablas}** | **{total.columnas}** | **{total.indices}** |")
    lines.append("")

    for nombre, tablas in grupos:
        lines += [f"## {nombre}", ""]
        for tabla in tablas:
            lines += [
                f"### `{tabla}`",
                "",
                "| Columna | Tipo | Nulo |",
                "|---|---|---|",
            ]
            lines += [
                f"| `{c.nombre}` | `{c.tipo}` | {'sí' if c.nullable else 'no'} |"
                for c in columnas_por_tabla[tabla]
            ]
            lines.append("")
            claves = sorted(restricciones_por_tabla.get(tabla, []), key=_orden_restriccion)
            if claves:
                lines += ["Claves: " + " · ".join(f"`{d}`" for d in claves), ""]
            indices = indices_por_relacion.get(tabla, [])
            if indices:
                lines += ["Índices: " + _lista_indices(indices), ""]

    lines += _seccion_relaciones(
        "Vistas materializadas", "Vista materializada", esquema.matviews, indices_por_relacion
    )
    lines += _seccion_relaciones("Vistas", "Vista", esquema.vistas, indices_por_relacion)

    return "\n".join(lines)


def _lista_indices(indices: Sequence[Indice]) -> str:
    return ", ".join(
        f"`{i.nombre}`" + (" (único)" if i.unico else "")
        for i in sorted(indices, key=lambda i: i.nombre)
    )


def _seccion_relaciones(
    titulo: str,
    encabezado: str,
    relaciones: Sequence[str],
    indices_por_relacion: dict[str, list[Indice]],
) -> list[str]:
    if not relaciones:
        return []
    lines = [f"## {titulo}", "", f"| {encabezado} | Índices |", "|---|---|"]
    for rel in sorted(relaciones):
        indices = indices_por_relacion.get(rel, [])
        lines.append(f"| `{rel}` | {_lista_indices(indices) if indices else '—'} |")
    lines.append("")
    return lines


# ─────────────────────────── lectura del catálogo ───────────────────────────

# `data_type` vale `USER-DEFINED` para los tipos de extensión: la columna de
# embeddings saldría con esa etiqueta opaca en lugar de `vector`, que es lo que
# el lector necesita saber. `udt_name` sí trae el nombre real.
_SQL_COLUMNAS = """
    SELECT c.table_name,
           c.column_name,
           CASE WHEN c.data_type = 'USER-DEFINED' THEN c.udt_name ELSE c.data_type END,
           c.is_nullable
      FROM information_schema.columns AS c
      JOIN information_schema.tables AS t
        ON t.table_schema = c.table_schema AND t.table_name = c.table_name
     WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'
     ORDER BY c.table_name, c.ordinal_position
"""

_SQL_RESTRICCIONES = """
    SELECT rel.relname, pg_get_constraintdef(con.oid)
      FROM pg_constraint AS con
      JOIN pg_class AS rel ON rel.oid = con.conrelid
      JOIN pg_namespace AS ns ON ns.oid = rel.relnamespace
     WHERE ns.nspname = 'public' AND con.contype IN ('p', 'u')
"""

# `pg_indexes` no distingue el índice que alguien declaró del que Postgres creó
# solo para respaldar una constraint; el anti-join con `pg_constraint` deja los
# primeros, que son los que dicen algo que no esté ya en la línea de claves.
# `starts_with` y no `LIKE 'CREATE UNIQUE%'`: psycopg trata `%` como marcador de
# formato en cuanto la consulta lleva parámetros, y una consulta que se rompe al
# añadirle el primer parámetro es una trampa para el siguiente que la toque.
_SQL_INDICES = """
    SELECT i.tablename, i.indexname, starts_with(i.indexdef, 'CREATE UNIQUE')
      FROM pg_indexes AS i
      LEFT JOIN pg_constraint AS con
        ON con.conname = i.indexname AND con.connamespace = 'public'::regnamespace
     WHERE i.schemaname = 'public' AND con.conname IS NULL
"""

_SQL_MATVIEWS = "SELECT matviewname FROM pg_matviews WHERE schemaname = 'public'"

_SQL_VISTAS = "SELECT table_name FROM information_schema.views WHERE table_schema = 'public'"

_SQL_REVISION = "SELECT version_num FROM alembic_version ORDER BY version_num"


class _Error(Exception):
    """Fallo que impide generar: no hay BD, o Alembic no llega a ``head``."""

    def __init__(self, mensaje: str, detalle: str = "") -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.detalle = detalle


def _dsn() -> str:
    """DSN de la base sobre la que migrar. Igual que ``tests/conftest.py``."""
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if url:
        return url
    env_file = _ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("TEST_DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise _Error(
        "TEST_DATABASE_URL no configurada (ni en el entorno ni en .env): "
        "este generador necesita un Postgres real sobre el que aplicar "
        "`alembic upgrade head`. Ejemplo:\n"
        "  TEST_DATABASE_URL=postgresql://tenderflow:tenderflow@localhost:5432/tenderflow"
    )


def _migrar(dsn: str) -> None:
    proceso = subprocess.run(  # argv fijo y sin shell: no hay entrada de usuario
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_ROOT,
        env={**os.environ, "DATABASE_URL": dsn, "ENV": "dev", "APP_PROFILE": "scraper"},
        capture_output=True,
        text=True,
        check=False,
    )
    if proceso.returncode != 0:
        raise _Error("`alembic upgrade head` falló sobre TEST_DATABASE_URL", proceso.stderr)


def leer_esquema(dsn: str) -> Esquema:
    """Aplica las migraciones y devuelve el catálogo resultante."""
    _migrar(dsn)
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise _Error("psycopg no está instalado; no se puede leer el catálogo") from exc

    try:
        with psycopg.connect(dsn) as conn:
            columnas = tuple(
                Columna(tabla=str(t), nombre=str(n), tipo=str(d), nullable=(str(x) == "YES"))
                for t, n, d, x in conn.execute(_SQL_COLUMNAS).fetchall()
            )
            restricciones = tuple(
                Restriccion(tabla=str(t), definicion=str(d))
                for t, d in conn.execute(_SQL_RESTRICCIONES).fetchall()
            )
            indices = tuple(
                Indice(relacion=str(r), nombre=str(n), unico=bool(u))
                for r, n, u in conn.execute(_SQL_INDICES).fetchall()
            )
            matviews = tuple(str(r[0]) for r in conn.execute(_SQL_MATVIEWS).fetchall())
            vistas = tuple(str(r[0]) for r in conn.execute(_SQL_VISTAS).fetchall())
            revisiones = [str(r[0]) for r in conn.execute(_SQL_REVISION).fetchall()]
    except Exception as exc:
        raise _Error("no se pudo leer el catálogo de TEST_DATABASE_URL", str(exc)) from exc

    return Esquema(
        revision=", ".join(revisiones) or "desconocida",
        columnas=columnas,
        restricciones=restricciones,
        indices=indices,
        matviews=matviews,
        vistas=vistas,
    )


# ──────────────────────────────── comparación ────────────────────────────────


def sin_fecha(texto: str) -> str:
    """La fecha cambia cada día; ``--check`` compara todo lo demás."""
    return re.sub(r"^Generado: .*$", "", texto, flags=re.MULTILINE)


def diferencias(actual: str, esperado: str) -> list[str]:
    """Diff unificado entre lo commiteado y lo derivado. Vacío si coinciden."""
    if sin_fecha(actual) == sin_fecha(esperado):
        return []
    return list(
        difflib.unified_diff(
            actual.splitlines(),
            esperado.splitlines(),
            fromfile="docs/database-schema.md (commiteado)",
            tofile="docs/database-schema.md (derivado de la BD)",
            lineterm="",
        )
    )


def main(argv: list[str]) -> int:
    try:
        esquema = leer_esquema(_dsn())
    except _Error as err:
        print(f"gen_schema_doc: {err.mensaje}", file=sys.stderr)
        if err.detalle:
            print(err.detalle, file=sys.stderr)
        return _SIN_BD

    contenido = render(esquema)

    if "--check" in argv:
        if not _OUT.exists():
            print(f"{_OUT} no existe. Ejecuta: make schema-doc", file=sys.stderr)
            return 1
        diff = diferencias(_OUT.read_text(encoding="utf-8"), contenido)
        if diff:
            print(
                f"{_OUT.relative_to(_ROOT)} está desfasado respecto al esquema. "
                "Ejecuta: make schema-doc",
                file=sys.stderr,
            )
            print("\n".join(diff), file=sys.stderr)
            return 1
        print(f"{_OUT} sincronizado.")
        return 0

    _OUT.write_text(contenido, encoding="utf-8")
    print(f"Escrito {_OUT.relative_to(_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
