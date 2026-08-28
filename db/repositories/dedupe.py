"""SQL del detector de reemisiones (ADR-022).

``services/dedupe.py`` está en la whitelist TID251 de ``pyproject.toml``, pero
esa entrada exime **abrir conexiones**, no la ubicación del SQL: AGENTS.md §3.10
y ADR-022 dicen que todo el SQL vive en ``db/``, y la whitelist está declarada
congelada (solo se quitan líneas). Así que las consultas del detector de
reemisiones nacen aquí y en ``services/`` se queda lo que es lógica de dominio:
agrupar por clave y elegir canónica.

Las tres funciones de este módulo tienen un invariante compartido con
``db/repositories/publico.py`` que es la razón de ser del fichero:

**El índice de candidatas se filtra con el mismo predicado de publicabilidad
que la superficie pública.** Antes no era así, y el modo de fallo era grave y
silencioso: el detector podía proponer como canónica una fila que la superficie
pública **no publica** (título corto, sin importe ni descripción), un humano
confirmaba el par desde ``resolve_pending``, ``exclude_duplicados_sql`` escondía
la duplicada… y el contrato desaparecía entero de la superficie. Es exactamente
el fallo que ``test_la_subconsulta_filtra_la_fila_gemela_igual_que_la_exterior``
protege en el lado SQL y que nadie protegía en el lado Python.

Tampoco se restringe el índice a una sola fuente. La proyección pública compara
``licitaciones l2`` sin filtro de fuente —colapsa PLACSP contra PSCP—, así que
un índice acotado a ``fuente = %s`` dejaba fuera pares que el SQL sí colapsa.
La fuente sigue acotando **las filas nuevas** que se evalúan, que es lo que hace
incremental al job.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from db.database import connect, connect_read
from db.repositories.base import rows_to_dicts

# Importa el privado a propósito. `_publicable_sql` es la definición de qué hace
# publicable a una fila (umbral de sustancia + dedupe ya marcado) y una segunda
# copia aquí sería justo la divergencia que el docstring de `_sustancia_sql`
# dice temer: el día que el umbral cambie en un sitio y no en el otro, el
# detector volvería a proponer canónicas que la superficie no publica.
from db.repositories.publico import _publicable_sql
from db.sql_fragments import organo_normalizado_sql

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

#: Columnas ligeras que necesita el matching. Se enumeran una sola vez porque
#: las dos consultas tienen que traer exactamente las mismas: si divergieran, el
#: índice y las filas nuevas se compararían con claves construidas de distinta
#: forma y el detector marcaría pares que no existen.
_COLUMNAS = (
    "l.id_externo, l.organo_contratacion, l.titulo, l.cpv, l.fuente, "
    "l.fecha_publicacion, l.fecha_extraccion"
)


def filas_nuevas_de_fuente(fuente: str, watermark: str) -> list[dict[str, Any]]:
    """Filas de ``fuente`` extraídas después del watermark del cursor.

    Sin filtro de publicabilidad: una fila que hoy no se publica puede ser
    reemisión de una que sí, y marcarla es correcto (esconde la copia pobre y
    deja viva la buena). Lo que no puede ocurrir es lo contrario, y de eso se
    ocupa el filtro del índice.
    """
    with connect_read() as c:
        return rows_to_dicts(
            c.execute(
                f"SELECT {_COLUMNAS} FROM licitaciones l "
                "WHERE l.fuente = %s AND l.fecha_extraccion > %s",
                (fuente, watermark),
            )
        )


def iter_filas_publicables_de_organos(organos_plegados: Sequence[str]) -> Iterator[dict[str, Any]]:
    """Filas **publicables** cuyo órgano plegado está en la lista, de cualquier fuente.

    ``organos_plegados`` son los órganos de las filas nuevas pasados por
    ``db.sql_fragments.plegar_organo``, que es el gemelo exacto de
    ``organo_normalizado_sql``. Acotar por ahí es lo que evita el pico de
    memoria del diseño anterior, que materializaba la fuente entera —~1,7 M
    filas para PSCP— como lista de dicts en cada pasada con al menos una fila
    nueva. Es la misma clase de fallo que el postmortem de ``OOM Render
    2026-07-14`` que cita ``services/_data_cache.py``.

    **El pico no queda eliminado, queda acotado**: la primera pasada sobre una
    fuente sin cursor trae todos los órganos, y el driver materializa el
    resultado en cliente aunque esto sea un generador. Lo que sí se evita es la
    segunda copia —la lista de dicts, mucho más pesada que las tuplas del
    cursor— y, en régimen incremental, la lista de órganos es corta. El arreglo
    definitivo es un cursor de servidor.
    """
    if not organos_plegados:
        return
    sql = (
        f"SELECT {_COLUMNAS} FROM licitaciones l "
        f"WHERE {organo_normalizado_sql('l')} = ANY(%s) AND {_publicable_sql('l')}"
    )
    with connect_read() as c:
        cur = c.execute(sql, (list(organos_plegados),))
        columnas = [d[0] for d in cur.description]
        for fila in cur:
            yield dict(zip(columnas, fila, strict=False))


def marcar_duplicados(marcas: Sequence[tuple[str, str, str, float, str]]) -> int:
    """Registra pares (duplicada, canónica) en ``licitaciones_duplicados``.

    ``ON CONFLICT DO NOTHING``: la primera marca de una fila manda. Reejecutar
    el job no puede reescribir un par que un humano ya resolvió, que es lo que
    hace que ejecutarlo sea reversible y barato.
    """
    if not marcas:
        return 0
    with connect() as c:
        c.executemany(
            "INSERT INTO licitaciones_duplicados "
            "(licitacion_id, canonical_id, clave_match, confianza, status) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT(licitacion_id) DO NOTHING",
            list(marcas),
        )
    return len(marcas)


__all__ = [
    "filas_nuevas_de_fuente",
    "iter_filas_publicables_de_organos",
    "marcar_duplicados",
]
