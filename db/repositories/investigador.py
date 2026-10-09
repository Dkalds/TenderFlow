"""SQL de la búsqueda por texto del Investigador: anuncios y pliegos.

Hasta 2026-10 la ruta ``/search/semantic`` buscaba con
``websearch_to_tsquery`` —todas las palabras a la vez— y, si no salía nada,
con un ``ILIKE`` del primer token de cuatro letras de la consulta cruda.
Medido contra producción el 2026-10-09: una pregunta normal no casaba con
nada, el último recurso buscaba «Puedes» o «licitaciones» sobre una columna
sin índice (5,4 s) y devolvía filas sin orden. Y el ámbito se aplicaba después,
contra un conjunto de 5.000 ids sin ordenar, frente a comunidades de 60.000
filas.

Lo que hay aquí:

- :func:`anuncios_por_terminos` — basta casar **alguno** de los términos, y el
  orden lo da cuánto pesan los que casan (los raros pesan más) y, a igualdad,
  ``ts_rank_cd``. Quien casa con todos queda arriba sin una pasada aparte, y
  cada fila dice qué términos le faltan.
- :func:`anuncios_por_expresion` — la consulta trae comillas o ``-exclusión``:
  se respeta entera con ``websearch_to_tsquery``.
- :func:`licitaciones_con_pasaje` y :func:`mejores_pasajes` — expedientes con
  algún fragmento de pliego que contiene todos los términos, y ese fragmento.
  ``documento_chunks`` tiene su propio GIN de texto desde v56 y nadie lo
  consultaba: la búsqueda miraba el anuncio, nunca el pliego.
- :func:`anuncios_literales` — último recurso por subcadena, sobre los GIN
  trigram del texto plegado (los mismos del listado).
- :func:`anuncios_del_ambito` — sin texto que buscar: lo más reciente del
  ámbito.

En todos el ámbito va **en el WHERE** (``ambito_busqueda_sql``): el orden se
calcula ya dentro de él.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from db.database import connect_read
from db.repositories.base import ambito_busqueda_sql, rows_to_dicts
from db.search_backend import TS_RANK_NORMALIZATION, TS_RANK_WEIGHTS
from db.sql_fragments import FOLD_TABLE, fold_expr

__all__ = [
    "MARCA_FIN",
    "MARCA_INICIO",
    "Ambito",
    "anuncios_del_ambito",
    "anuncios_literales",
    "anuncios_por_expresion",
    "anuncios_por_id",
    "anuncios_por_terminos",
    "licitaciones_con_pasaje",
    "mejores_pasajes",
]

#: Delimitadores que ``ts_headline`` pone alrededor de lo que casa. Dos
#: caracteres del área de uso privado de Unicode: no aparecen en un pliego, y
#: quien los recibe los convierte en tramos tipados antes de que salgan de la
#: API (``services.investigador.busqueda``). No son HTML a propósito: el texto
#: del extracto es de terceros y nunca se interpreta como marcado.
MARCA_INICIO = ""
MARCA_FIN = ""

#: Opciones de ``ts_headline``: hasta dos fragmentos cortos alrededor de lo que
#: casa. Si nada casa, devuelve el arranque del texto.
_OPCIONES_EXTRACTO = (
    f"StartSel={MARCA_INICIO}, StopSel={MARCA_FIN}, "
    'MaxFragments=2, MaxWords=28, MinWords=12, FragmentDelimiter=" … "'
)

#: Opciones para marcar el título entero, sin recortarlo.
_OPCIONES_TITULO = f"StartSel={MARCA_INICIO}, StopSel={MARCA_FIN}, HighlightAll=true"

#: Texto del anuncio sobre el que se calcula el extracto. Acotado: hay
#: descripciones de cientos de KB y ``ts_headline`` cuesta en proporción.
_TEXTO_ANUNCIO = "left(COALESCE(NULLIF(l.descripcion, ''), l.titulo, ''), 20000)"

_COLUMNAS = (
    "l.id_externo, l.titulo, l.organo_contratacion, l.importe, l.descripcion, l.url, "
    "l.fecha_publicacion, l.fecha_limite, l.ccaa, l.estado, l.tecnologia"
)

_RANK = f"'{TS_RANK_WEIGHTS}'::float4[]"

#: Términos que entran en el último recurso por subcadena, como mucho, y su
#: longitud mínima: un patrón de menos de tres letras no puede usar el índice
#: trigram y recorrería la tabla.
_MAX_TERMINOS_LITERALES = 4
_MIN_LETRAS_LITERAL = 3


@dataclass(frozen=True)
class Ambito:
    """Los filtros que acotan una búsqueda del Investigador."""

    ccaa: tuple[str, ...] = ()
    #: Comunidades que salieron de la frase («en Galicia»), no de la barra de
    #: ámbito. Acotan igual, con una diferencia: una fila **sin** comunidad
    #: informada pasa si su texto la nombra. Quien escribe «en Galicia» no
    #: puede saber que al expediente de la Xunta le falta la columna, y un
    #: filtro que lo escondiera fallaría sin que nadie lo viera.
    ccaa_del_texto: tuple[str, ...] = ()
    tecnologia: tuple[str, ...] = ()
    fecha_desde: str | None = None
    fecha_hasta: str | None = None
    importe_min: float | None = None
    importe_max: float | None = None
    solo_abiertas: bool = False

    def sql(self, alias: str = "l") -> tuple[list[str], list[Any]]:
        """``(cláusulas, parámetros)`` del ámbito sobre ``licitaciones``."""
        clausulas: list[str] = []
        valores: list[Any] = []
        if self.ccaa_del_texto:
            una = (
                f"({alias}.ccaa = %s OR (COALESCE({alias}.ccaa, '') = '' "
                f"AND {alias}.search_vector @@ plainto_tsquery('spanish', %s)))"
            )
            clausulas.append("(" + " OR ".join([una] * len(self.ccaa_del_texto)) + ")")
            valores.extend(v for nombre in self.ccaa_del_texto for v in (nombre, nombre))
        resto, valores_resto = ambito_busqueda_sql(
            alias,
            ccaa=list(self.ccaa),
            tecnologia=list(self.tecnologia),
            fecha_desde=self.fecha_desde,
            fecha_hasta=self.fecha_hasta,
            importe_min=self.importe_min,
            importe_max=self.importe_max,
            solo_abiertas=self.solo_abiertas,
        )
        return [*clausulas, *resto], [*valores, *valores_resto]

    @property
    def vacio(self) -> bool:
        return not self.sql()[0]


def _y(clausulas: Sequence[str]) -> str:
    """``AND a AND b`` para añadir a un WHERE que ya tiene condición, o ``""``."""
    return "".join(f" AND {c}" for c in clausulas)


def anuncios_por_terminos(
    terminos: Sequence[str],
    ambito: Ambito,
    *,
    limit: int,
    recientes: bool = False,
) -> list[dict[str, Any]]:
    """Anuncios que casan con alguno de ``terminos``, los más completos primero.

    Cada término se normaliza con el diccionario español en la propia consulta
    (``plainto_tsquery``): los que son palabras vacías desaparecen y dos formas
    de la misma palabra («licencia», «licencias») cuentan como una.

    El orden es la suma de los pesos de los términos que casan, y el peso de un
    término crece con lo raro que es **entre los candidatos** de esta misma
    consulta. Así un expediente que casa con todos va delante, y entre los que
    casan a medias gana el que tiene la palabra que distingue («temeraria»), no
    el que tiene la que está en todas partes («servicio»). A igualdad,
    ``ts_rank_cd`` con los pesos de ``db.search_backend`` (título por delante
    de la descripción).

    Con ``recientes`` van primero los que casan con todos y, dentro, los de
    publicación más reciente.

    Cada fila trae ``cobertura`` (términos que casan), ``n_terminos``,
    ``ausentes`` (los que no) y ``extracto`` (con :data:`MARCA_INICIO` y
    :data:`MARCA_FIN` alrededor de lo que casa).

    Las CTE van ``MATERIALIZED`` a propósito. Postgres incrusta la que solo se
    usa en un sitio, y ``pesos`` se usa en una subconsulta **por candidato**:
    incrustada, recalculaba la frecuencia de cada término para cada fila
    —cuadrático—, y «licencia» (7.950 candidatos) caducaba a los 30 s contra
    producción. Calculada una vez, la misma consulta tarda 89 ms.
    """
    if not terminos:
        return []
    clausulas, valores = ambito.sql("l")
    orden = (
        "(cardinality(c.casados) = (SELECT count(*) FROM terminos)) DESC, "
        "c.fpub DESC NULLS LAST, c.id_externo"
        if recientes
        else "puntos DESC, c.rank DESC, c.id_externo"
    )
    orden_final = (
        "(cardinality(o.casados) = (SELECT count(*) FROM terminos)) DESC, "
        "l.fecha_publicacion DESC NULLS LAST, o.id_externo"
        if recientes
        else "o.puntos DESC, o.rank DESC, o.id_externo"
    )
    sql = f"""
        WITH terminos AS MATERIALIZED (
            SELECT min(u.o) AS ord, min(u.t) AS termino, lex::text AS lex_txt
            FROM unnest(%s::text[]) WITH ORDINALITY AS u(t, o)
            CROSS JOIN LATERAL plainto_tsquery('spanish', u.t) AS lex
            WHERE numnode(lex) > 0
            GROUP BY lex::text
        ),
        consulta AS MATERIALIZED (
            SELECT string_agg('(' || lex_txt || ')', ' | ')::tsquery AS q FROM terminos
        ),
        cand AS MATERIALIZED (
            SELECT l.id_externo, l.fecha_publicacion AS fpub,
                   ARRAY(
                       SELECT t.ord FROM terminos t
                       WHERE l.search_vector @@ t.lex_txt::tsquery
                   ) AS casados,
                   ts_rank_cd({_RANK}, l.search_vector, c.q, {TS_RANK_NORMALIZATION}) AS rank
            FROM consulta c
            JOIN licitaciones l ON l.search_vector @@ c.q
            WHERE TRUE{_y(clausulas)}
        ),
        frecuencia AS MATERIALIZED (
            SELECT ord, count(*) AS n FROM cand, unnest(casados) AS ord GROUP BY ord
        ),
        pesos AS MATERIALIZED (
            SELECT f.ord, ln(1.0 + (SELECT count(*) FROM cand)::float8 / f.n) AS peso
            FROM frecuencia f
        ),
        ordenadas AS (
            SELECT c.id_externo, c.casados, c.rank,
                   (SELECT COALESCE(sum(p.peso), 0) FROM pesos p WHERE p.ord = ANY(c.casados))
                       AS puntos
            FROM cand c
            ORDER BY {orden}
            LIMIT %s
        )
        SELECT {_COLUMNAS},
               o.puntos, o.rank,
               cardinality(o.casados) AS cobertura,
               (SELECT count(*) FROM terminos) AS n_terminos,
               ARRAY(
                   SELECT t.termino FROM terminos t
                   WHERE NOT (t.ord = ANY(o.casados)) ORDER BY t.ord
               ) AS ausentes,
               ts_headline('spanish', COALESCE(l.titulo, ''), (SELECT q FROM consulta), %s)
                   AS titulo_marcado,
               ts_headline('spanish', {_TEXTO_ANUNCIO}, (SELECT q FROM consulta), %s) AS extracto
        FROM ordenadas o
        JOIN licitaciones l ON l.id_externo = o.id_externo
        ORDER BY {orden_final}
    """
    with connect_read() as c:
        cur = c.execute(
            sql, [list(terminos), *valores, limit, _OPCIONES_TITULO, _OPCIONES_EXTRACTO]
        )
        return rows_to_dicts(cur)


def anuncios_por_expresion(
    expresion: str,
    ambito: Ambito,
    *,
    limit: int,
    recientes: bool = False,
) -> list[dict[str, Any]]:
    """Anuncios que casan con ``expresion`` entera (``websearch_to_tsquery``).

    Para la consulta que trae comillas («gestión documental») o una exclusión
    (``-obra``): quien las escribe quiere exactamente eso, no «alguna de estas
    palabras». Sin relajación.
    """
    if not expresion.strip():
        return []
    clausulas, valores = ambito.sql("l")
    tsq = "websearch_to_tsquery('spanish', %s)"
    orden = (
        "l.fecha_publicacion DESC NULLS LAST, l.id_externo"
        if recientes
        else "rank DESC, l.id_externo"
    )
    orden_final = (
        "l.fecha_publicacion DESC NULLS LAST, o.id_externo"
        if recientes
        else "o.rank DESC, o.id_externo"
    )
    sql = f"""
        WITH ordenadas AS (
            SELECT l.id_externo,
                   ts_rank_cd({_RANK}, l.search_vector, {tsq}, {TS_RANK_NORMALIZATION}) AS rank
            FROM licitaciones l
            WHERE l.search_vector @@ {tsq}{_y(clausulas)}
            ORDER BY {orden}
            LIMIT %s
        )
        SELECT {_COLUMNAS}, o.rank,
               ts_headline('spanish', COALESCE(l.titulo, ''), {tsq}, %s) AS titulo_marcado,
               ts_headline('spanish', {_TEXTO_ANUNCIO}, {tsq}, %s) AS extracto
        FROM ordenadas o
        JOIN licitaciones l ON l.id_externo = o.id_externo
        ORDER BY {orden_final}
    """
    with connect_read() as c:
        cur = c.execute(
            sql,
            [
                expresion,
                expresion,
                *valores,
                limit,
                expresion,
                _OPCIONES_TITULO,
                expresion,
                _OPCIONES_EXTRACTO,
            ],
        )
        return rows_to_dicts(cur)


def _tsquery_de_pasaje(expresion: bool) -> str:
    """La tsquery de un pasaje: la expresión tal cual, o todos los términos."""
    funcion = "websearch_to_tsquery" if expresion else "plainto_tsquery"
    return f"{funcion}('spanish', %s)"


def licitaciones_con_pasaje(
    texto: str,
    ambito: Ambito,
    *,
    expresion: bool = False,
    limite_pasajes: int = 2000,
    limit: int = 50,
) -> list[tuple[str, int]]:
    """Expedientes con algún fragmento de pliego que contiene **todo** ``texto``.

    ``[(id_externo, pasajes)]``, primero los que tienen más fragmentos que
    casan. Dentro de un fragmento se exigen todos los términos: uno solo, sobre
    345.000 fragmentos, casa con decenas de miles y no dice nada.

    ``limite_pasajes`` acota los fragmentos que se llegan a mirar. Un término
    muy común («mantenimiento», 37.000 fragmentos) no puede convertir una
    búsqueda en un recorrido de la tabla; con el tope, el recuento de esos
    casos es de una muestra, y el expediente sigue apareciendo.
    """
    if not texto.strip():
        return []
    clausulas, valores = ambito.sql("l")
    tsq = _tsquery_de_pasaje(expresion)
    join_ambito = "JOIN licitaciones l ON l.id_externo = d.licitacion_id " if clausulas else ""
    sql = f"""
        SELECT m.licitacion_id, count(*) AS pasajes
        FROM (
            SELECT d.licitacion_id
            FROM documento_chunks dc
            JOIN documentos d ON d.id = dc.documento_id
            {join_ambito}
            WHERE dc.search_vector @@ {tsq}{_y(clausulas)}
            LIMIT %s
        ) m
        GROUP BY m.licitacion_id
        ORDER BY pasajes DESC, m.licitacion_id
        LIMIT %s
    """
    with connect_read() as c:
        filas = c.execute(sql, [texto, *valores, limite_pasajes, limit]).fetchall()
    return [(str(f[0]), int(f[1])) for f in filas]


def mejores_pasajes(
    ids: Sequence[str], texto: str, *, expresion: bool = False
) -> dict[str, dict[str, Any]]:
    """El mejor fragmento de pliego de cada expediente de ``ids`` para ``texto``.

    Por ``id_externo``: ``documento_id``, ``tipo``, ``filename``,
    ``chunk_index``, ``page_number``, ``texto`` (el fragmento entero, que es lo
    que cita ``/ask``) y ``extracto`` (con las marcas alrededor de lo que casa).

    El extracto se calcula fuera del ``DISTINCT ON``: dentro se calcularía para
    cada fragmento candidato y solo se conserva uno por expediente.
    """
    if not ids or not texto.strip():
        return {}
    tsq = _tsquery_de_pasaje(expresion)
    sql = f"""
        WITH mejores AS (
            SELECT DISTINCT ON (d.licitacion_id)
                   d.licitacion_id, d.id AS documento_id, d.tipo, d.filename, dc.id AS chunk_id
            FROM documento_chunks dc
            JOIN documentos d ON d.id = dc.documento_id
            WHERE d.licitacion_id = ANY(%s) AND dc.search_vector @@ {tsq}
            ORDER BY d.licitacion_id, ts_rank_cd(dc.search_vector, {tsq}) DESC, dc.id
        )
        SELECT m.licitacion_id, m.documento_id, m.tipo, m.filename,
               dc.chunk_index, dc.page_number, dc.texto,
               ts_headline('spanish', dc.texto, {tsq}, %s) AS extracto
        FROM mejores m
        JOIN documento_chunks dc ON dc.id = m.chunk_id
    """
    with connect_read() as c:
        cur = c.execute(sql, [list(ids), texto, texto, texto, _OPCIONES_EXTRACTO])
        filas = rows_to_dicts(cur)
    return {str(f["licitacion_id"]): f for f in filas}


def anuncios_por_id(ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Las columnas de resultado de los expedientes de ``ids``, por ``id_externo``."""
    if not ids:
        return {}
    with connect_read() as c:
        cur = c.execute(
            f"SELECT {_COLUMNAS} FROM licitaciones l WHERE l.id_externo = ANY(%s)",
            [list(ids)],
        )
        return {str(f["id_externo"]): f for f in rows_to_dicts(cur)}


def _patron(termino: str) -> str:
    """``termino`` plegado, con sus comodines escapados, como subcadena."""
    limpio = termino.strip().translate(FOLD_TABLE).lower()
    escapado = limpio.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escapado}%"


def anuncios_literales(
    terminos: Sequence[str], ambito: Ambito, *, limit: int
) -> list[dict[str, Any]]:
    """Anuncios cuyo título o descripción contienen alguno de ``terminos``.

    Último recurso, para lo que el diccionario no encuentra: una palabra a
    medias o un código pegado a otra cosa. Compara el texto plegado —sin
    tildes ni mayúsculas, con la expresión de ``fold_expr``— para que resuelvan
    los GIN trigram ``idx_lic_titulo_plegado_trgm`` e
    ``idx_lic_descripcion_plegada_trgm``; el ``ILIKE`` sobre la columna cruda
    que había antes no tenía índice para la descripción.

    Primero los que contienen más términos y, dentro, los más recientes: no hay
    relevancia que ordenar. ``cobertura`` y ``n_terminos`` cuentan sobre los
    términos que de verdad se buscaron (los de tres letras o más, hasta cuatro).
    """
    utiles = [t for t in terminos if len(t.strip()) >= _MIN_LETRAS_LITERAL]
    utiles = utiles[:_MAX_TERMINOS_LITERALES]
    if not utiles:
        return []
    clausulas, valores = ambito.sql("l")
    contiene = f"({fold_expr('l.titulo')} LIKE %s OR {fold_expr('l.descripcion')} LIKE %s)"
    cobertura = " + ".join([f"(CASE WHEN {contiene} THEN 1 ELSE 0 END)"] * len(utiles))
    alguno = " OR ".join([contiene] * len(utiles))
    patrones = [p for t in utiles for p in (_patron(t), _patron(t))]
    sql = f"""
        SELECT {_COLUMNAS}, {cobertura} AS cobertura, {len(utiles)} AS n_terminos
        FROM licitaciones l
        WHERE ({alguno}){_y(clausulas)}
        ORDER BY cobertura DESC, l.fecha_publicacion DESC NULLS LAST, l.id_externo
        LIMIT %s
    """
    with connect_read() as c:
        cur = c.execute(sql, [*patrones, *patrones, *valores, limit])
        return rows_to_dicts(cur)


def anuncios_del_ambito(ambito: Ambito, *, limit: int) -> list[dict[str, Any]]:
    """Lo más reciente del ámbito, sin texto: «abiertas en Madrid», «las últimas».

    Solo expedientes con fecha de publicación, y ordenados ``DESC`` a secas.
    No es un detalle: ``DESC NULLS LAST`` no es el orden de ningún recorrido de
    ``idx_fecha_pub`` (hacia atrás, un btree da ``DESC NULLS FIRST``), así que
    Postgres ordenaba la tabla entera —5,1 s medidos contra producción el
    2026-10-09—. Con el ``IS NOT NULL`` el recorrido hacia atrás del índice ya
    es el orden pedido y corta en el ``LIMIT``: 5 ms. Un expediente sin fecha
    de publicación no puede ser «lo más reciente» de nada.
    """
    clausulas, valores = ambito.sql("l")
    donde = " AND ".join(["l.fecha_publicacion IS NOT NULL", *clausulas])
    sql = (
        f"SELECT {_COLUMNAS} FROM licitaciones l WHERE {donde} "
        "ORDER BY l.fecha_publicacion DESC, l.id_externo LIMIT %s"
    )
    with connect_read() as c:
        cur = c.execute(sql, [*valores, limit])
        return rows_to_dicts(cur)
