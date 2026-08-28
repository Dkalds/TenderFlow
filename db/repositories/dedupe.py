"""SQL de los detectores de duplicados y reemisiones (ADR-022).

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

El detector *cross-fuente* (``detect_duplicates``) llegó después a este módulo,
por el mismo motivo y con el mismo modo de fallo: consultaba
``FROM licitaciones WHERE fuente != %s`` sin LIMIT ni watermark y lo
materializaba entero como lista de dicts en **cada** ingesta. Su índice se acota
por expediente natural —ver :func:`iter_filas_de_otras_fuentes_por_expediente`—
y no por órgano, porque ahí el emparejamiento sí exige expediente idéntico y
acotar por él no puede perder ningún par.
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
#: todas las consultas del módulo tienen que traer exactamente las mismas: si
#: divergieran, el índice y las filas nuevas se compararían con claves
#: construidas de distinta forma y el detector marcaría pares que no existen.
_COLUMNAS = (
    "l.id_externo, l.organo_contratacion, l.titulo, l.cpv, l.fuente, "
    "l.fecha_publicacion, l.fecha_extraccion"
)

#: Expediente natural: el ``id_externo`` sin el namespace de fuente (ADR-009).
#: Gemelo SQL de ``services.dedupe.natural_expediente`` — corta por el PRIMER
#: ``':'`` y devuelve el id entero cuando no hay separador, que es el caso de
#: PLACSP (sus ``id_externo`` no llevan prefijo). Si las dos definiciones
#: divergieran, el prefiltro de este módulo escondería pares que el matching de
#: Python sí considera, y el dedupe dejaría de ver duplicados sin decir nada.
_EXPEDIENTE_NATURAL_SQL = (
    "CASE WHEN position(':' in l.id_externo) > 0 "
    "THEN substr(l.id_externo, position(':' in l.id_externo) + 1) "
    "ELSE l.id_externo END"
)


def _iter_dicts(sql: str, params: tuple[Any, ...]) -> Iterator[dict[str, Any]]:
    """Recorre un SELECT sin construir la lista completa de dicts.

    Es la mitad barata de ``rows_to_dicts``: las **tuplas** sí se materializan
    —el adaptador de ``db/connection.py`` no expone cursor iterable, sólo
    ``fetchall``/``fetchone``, así que no hay streaming que aprovechar— pero no
    se añade encima una lista de dicts, que es varias veces más pesada y es la
    que provocaba el pico con la fuente entera. Ver
    :func:`iter_filas_publicables_de_organos`.

    Se escribió primero como ``for fila in cur``, que es lo natural con un
    cursor de psycopg y aquí lanza ``TypeError``: ``execute`` devuelve el
    adaptador, no el cursor.
    """
    with connect_read() as c:
        cur = c.execute(sql, params)
        columnas = [d[0] for d in cur.description]
        for fila in cur.fetchall():
            yield dict(zip(columnas, fila, strict=False))


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
    yield from _iter_dicts(sql, (list(organos_plegados),))


def iter_filas_de_otras_fuentes_por_expediente(
    fuente: str, expedientes: Sequence[str]
) -> Iterator[dict[str, Any]]:
    """Candidatas del dedupe cross-fuente: otras fuentes, expediente en la lista.

    ``detect_duplicates`` empareja fila nueva ↔ candidata exigiendo **expediente
    natural idéntico** (además de órgano). Acotar por los expedientes de las
    filas nuevas es por tanto una restricción sin pérdida: cualquier fila que el
    ``ANY`` deja fuera habría fallado igualmente la comparación en Python. Es lo
    que la distingue del prefiltro por órgano de
    :func:`iter_filas_publicables_de_organos`, que ahí sí puede plegar distinto
    que el matching y por eso vive acompañado del filtro de publicabilidad.

    Y es lo que sustituye al ``SELECT ... WHERE fuente != %s`` sin LIMIT ni
    watermark que había en ``services/dedupe.py``: ese traía la fuente entera
    —~1,7 M filas de PSCP— como lista de dicts en cada ingesta, con el llamador
    en modo fail-open, o sea que cuando reventaba por memoria la ingesta se
    declaraba exitosa igual.

    **No hay filtro de publicabilidad** aquí, al revés que en el detector de
    reemisiones. Este detector no elige canónica entre gemelas de la misma
    proyección: empareja el mismo expediente publicado por dos administraciones
    y la canónica la decide ``_rango_canonico`` (PLACSP primero). Filtrar por
    publicabilidad escondería el par en vez de marcarlo.

    El ``ANY`` sobre la expresión de expediente no usa índice —no existe uno
    funcional sobre ella—, así que sigue habiendo un recorrido de la tabla; lo
    que desaparece es el transporte y la materialización de millones de filas
    que el matching iba a descartar de todas formas.
    """
    if not expedientes:
        return
    sql = (
        f"SELECT {_COLUMNAS} FROM licitaciones l "
        f"WHERE l.fuente <> %s AND {_EXPEDIENTE_NATURAL_SQL} = ANY(%s)"
    )
    yield from _iter_dicts(sql, (fuente, list(expedientes)))


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
    "iter_filas_de_otras_fuentes_por_expediente",
    "iter_filas_publicables_de_organos",
    "marcar_duplicados",
]
