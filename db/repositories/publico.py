"""Repository de la superficie pública indexable.

Existe separado del de licitaciones por una razón concreta y no por gusto
arquitectónico: **las piezas que ya hay filtran analítica propia**.
``LicitacionRepository.get_by_id`` es un ``SELECT *``, así que devuelve
``ml_proba``, ``inclusion_reason``, ``filter_version`` y ``analysis_universe``
enteros; y ``_SUMMARY_COLS`` lleva horneadas ``ml_tecnologias``,
``ml_proba_max`` y ``ml_tech_principal``. Reutilizar cualquiera de las dos en
una ruta anónima publica el pipeline propio el primer día, con la respuesta
devolviendo 200 y sin que nada falle.

Por eso aquí la proyección es una **allowlist explícita de columnas**
(:data:`_COLS_PUBLICAS`). Un campo nuevo en la tabla no aparece en la superficie
pública solo por añadirse aguas arriba: hay que meterlo a mano en esa tupla, que
es justo el momento en el que alguien tiene que pensárselo.
``scripts/check_public_surface.py`` lo verifica en CI.

Qué NO sale de aquí, decidido con el dueño del producto:

- Nada de ``adjudicaciones``. El adjudicatario puede ser un autónomo, su ``nif``
  es entonces su DNI, y en el repositorio no existe ninguna lógica que
  distinga persona física de jurídica (``es_pyme`` no sirve: viene de
  ``SMEAwardedIndicator`` y marca a cualquier empresa pequeña). La tabla entera
  se queda privada.
- Ningún campo derivado del ML ni del linaje del pipeline.

**Una fila por contrato, no una por anuncio.** Las seis superficies indexables
—``listar``, ``contar``, ``ultima_incorporacion``, los dos hubs y el sitemap—
comparten ``_WHERE_INDEXABLE``, que además del umbral de sustancia colapsa las
reemisiones del mismo contrato. Comparten *la constante* y no una copia cada
una: el docstring de ``contar`` y el de ``pagina_de_sitemap`` ya explican qué
pasa cuando dos de estas consultas discrepan (error de cobertura en Search
Console, paginación hacia páginas vacías), y con seis call-sites la única
defensa que aguanta es que no haya dos textos que mantener.
"""

from __future__ import annotations

from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from db.sql_fragments import (
    FOLD_DST,
    FOLD_SRC,
    exclude_duplicados_sql,
    fila_canonica_sql,
)

__all__ = ["PublicoRepository"]


# ── Proyección pública ────────────────────────────────────────────────────
# Solo campos del anuncio oficial de PLACSP/TED, que ya es open data.
#
# Deliberadamente ausentes: ml_proba, ml_proba_max, ml_tecnologias,
# ml_tech_principal, tecnologia, raw_keywords, filter_version,
# classifier_model_version, inclusion_reason, analysis_universe (pipeline
# propio) y peso_precio_pct (de fuente, pero su propio comentario en
# db/models.py admite que lleva inferencia dentro).
#
# `url` y `fecha_extraccion` no son opcionales aunque lo parezcan: la Ley
# 37/2007 condiciona la reutilización a citar la fuente e indicar la fecha de
# la última actualización, así que ambos tienen que llegar a la página.
_COLS_PUBLICAS: tuple[str, ...] = (
    "id_externo",
    "titulo",
    "descripcion",
    "organo_contratacion",
    "importe",
    "moneda",
    "cpv",
    "tipo_contrato",
    "estado",
    "procedimiento",
    "tramitacion",
    "fecha_publicacion",
    "fecha_limite",
    "fecha_inicio",
    "fecha_fin",
    "duracion_valor",
    "duracion_unidad",
    "provincia",
    "ccaa",
    "nuts_code",
    "url",
    "fuente",
    "fecha_extraccion",
)

_SELECT_PUBLICO = ", ".join(f"l.{c}" for c in _COLS_PUBLICAS)

# ── Umbral de sustancia ───────────────────────────────────────────────────
# El mayor riesgo de un proyecto de SEO programático no es publicar poco: es
# publicar decenas de miles de páginas casi vacías, que hace que Google degrade
# el dominio entero y no solo esas URLs. Un expediente sin título utilizable, o
# sin nada que contar más allá del título, no llega a ser una página.
#
# El umbral es explícito y verificable en SQL para que la misma regla decida
# qué se indexa, qué entra en el sitemap y qué devuelve un 404: si el listado y
# el sitemap discreparan, Search Console lo reportaría como error de cobertura.
# Licitaciones mínimas para que una comunidad o un CPV merezcan página propia
# de índice. Por debajo de esto el hub es una lista de dos elementos: no aporta
# nada al visitante y cuenta como página de baja calidad del dominio.
_MIN_POR_HUB = 3

_MIN_CARACTERES_TITULO = 25
_MIN_CARACTERES_DESCRIPCION = 200


def _sustancia_sql(alias: str) -> str:
    """Umbral de sustancia escrito para un alias concreto.

    Está parametrizado por alias —y no es una constante con ``l`` dentro—
    porque el filtro de canónica necesita aplicar **el mismo** umbral a la fila
    gemela de la subconsulta. Si divergieran, una fila demasiado pobre para
    publicarse podría tapar a la buena y el contrato desaparecería entero.
    """
    return (
        f"{alias}.titulo IS NOT NULL AND length(trim({alias}.titulo)) >= {_MIN_CARACTERES_TITULO} "
        f"AND ({alias}.importe IS NOT NULL "
        f"OR length(coalesce({alias}.descripcion, '')) >= {_MIN_CARACTERES_DESCRIPCION})"
    )


def _publicable_sql(alias: str) -> str:
    """Sustancia + duplicado ya marcado. Lo que hace publicable a una fila."""
    # Publicar un duplicado es contenido duplicado —que Google penaliza— y
    # además presenta dos veces el mismo contrato al visitante.
    no_duplicados = exclude_duplicados_sql(alias + ".id_externo")
    return f"{_sustancia_sql(alias)} AND {no_duplicados}"


#: Publicabilidad de la fila, sin más. Es lo que aplica `ficha`.
_BASE_WHERE = _publicable_sql("l")

# ── Contrato canónico: una fila por contrato, no una por anuncio ──────────
# `exclude_duplicados_sql` solo excluye lo que el job de dedupe marcó como
# `confirmed`. Ese job es *cross-fuente* y su clave es el expediente natural,
# así que no ve el caso que de verdad ensucia esta superficie: la misma fuente
# reemitiendo el mismo contrato con otro `id_externo` (TED acuña un
# `publication-number` por anuncio; PSCP cae al `id` de la fila cuando el
# registro no trae `codi_expedient`). Resultado observado en la auditoría: el
# hub de Cataluña servía el mismo contrato dos veces en la primera página.
#
# De ahí que la proyección se defienda sola en vez de confiar en que el job
# haya corrido. La cláusula se compone una sola vez y la usan las **seis**
# superficies indexables. No es cosmética que compartan constante: si el
# listado y el sitemap discreparan, Search Console lo reporta como error de
# cobertura, y si `contar` discrepara del listado el hub paginaría hacia
# páginas vacías. `ficha` se queda fuera a propósito — ver su docstring.
#
# Coste: ver `fila_canonica_sql`. Resumen — hash anti-join sobre las ~586k
# filas publicables, sin índice que cubra la clave, y el listado ya no puede
# resolver su `ORDER BY ... LIMIT` por índice. Lo paga una revalidación ISR
# cacheada una hora, no cada visita.
_CANONICA_SQL = fila_canonica_sql(alias="l", gemelo="l2", filtro_gemelo=_publicable_sql("l2"))

#: Filtro de las seis superficies indexables. `_BASE_WHERE` es un superconjunto
#: suyo, nunca al revés: una URL del sitemap siempre tiene ficha.
_WHERE_INDEXABLE = f"{_BASE_WHERE} AND {_CANONICA_SQL}"

# ── Resolución del slug de comunidad autónoma ─────────────────────────────
# El hub `/licitaciones/comunidad-valenciana` recibe un slug, no el nombre. La
# traducción ocurre **en Postgres** y no con una tabla en el frontend, por dos
# razones: el invariante 3 de `web/AGENTS.md` prohíbe hardcodear en el cliente
# listas que el backend debe proveer, y sobre todo porque una tabla escrita a
# mano divergiría del valor real de la columna en cuanto la fuente publicara
# una grafía nueva — y el hub devolvería vacío sin que nada fallara.
#
# Los pares de plegado viven en `db/sql_fragments.py` desde que el filtro de
# canónica los necesita también: eran una copia local de los de `_fold_expr`
# (`db/repositories/aggregates.py`, privados de aquel módulo) y una tercera
# copia era una divergencia esperando a ocurrir.

#: Slug de `l.ccaa` calculado en SQL, equivalente a `slugificar()` de
#: `web/src/lib/slug.ts`. Las dos implementaciones tienen que coincidir o el
#: enlace que genera el frontend apuntaría a un hub que no encuentra nada.
_CCAA_SLUG_SQL = (
    "trim(both '-' from regexp_replace("
    f"lower(translate(coalesce(l.ccaa, ''), '{FOLD_SRC}', '{FOLD_DST}')), "
    "'[^a-z0-9]+', '-', 'g'))"
)


class PublicoRepository:
    """Lecturas de la superficie pública. Solo SELECT, solo campos de fuente."""

    def ficha(self, id_externo: str, *, conn: Any | None = None) -> dict[str, Any] | None:
        """Devuelve el anuncio público de un expediente, o ``None``.

        ``None`` cubre tres casos que para el visitante son el mismo 404: el
        expediente no existe, es un duplicado ya marcado, o no supera el umbral
        de sustancia. Que un expediente delgado devuelva 404 y no una página
        pobre es intencionado — es la mitad de la defensa contra el contenido
        delgado; la otra mitad es que tampoco entra en el sitemap.

        Aplica ``_BASE_WHERE`` y **no** el filtro de canónica de las superficies
        indexables, que es un subconjunto suyo. La asimetría es a favor de
        seguridad y va en el único sentido que no rompe nada: toda URL del
        sitemap tiene ficha. Al revés —404 en algo que el índice ya conoce—
        sería una oleada de errores de cobertura en Search Console. La fila
        gemela no canónica sigue respondiendo 200, pero no la enlaza nadie ni
        entra en el sitemap, así que no compite por indexación. Marcarla con
        ``rel=canonical`` es trabajo del frontend, no de esta capa.
        """
        sql = f"SELECT {_SELECT_PUBLICO} FROM licitaciones l WHERE l.id_externo = %s AND {_BASE_WHERE}"

        def _consultar(c: Any) -> dict[str, Any] | None:
            filas = rows_to_dicts(c.execute(sql, (id_externo,)))
            return filas[0] if filas else None

        if conn is not None:
            return _consultar(conn)
        with connect_read() as c:
            return _consultar(c)

    def lotes_de(self, id_externo: str, *, conn: Any | None = None) -> list[dict[str, Any]]:
        """Lotes del expediente. La tabla ``lotes`` no tiene campos de persona."""
        sql = (
            "SELECT numero, titulo, cpv, importe, fecha_limite FROM lotes "
            "WHERE licitacion_id = %s ORDER BY numero"
        )

        def _consultar(c: Any) -> list[dict[str, Any]]:
            return rows_to_dicts(c.execute(sql, (id_externo,)))

        if conn is not None:
            return _consultar(conn)
        with connect_read() as c:
            return _consultar(c)

    def listar(
        self,
        *,
        ccaa_slug: str | None = None,
        cpv_prefijo: str | None = None,
        limite: int = 50,
        desplazamiento: int = 0,
        conn: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Listado público para los hubs, del más reciente al más antiguo.

        Una fila por contrato: el filtro de canónica impide que el mismo
        anuncio reemitido aparezca dos veces en la misma página, que es lo que
        hacía el hub de Cataluña.
        """
        condiciones = [_WHERE_INDEXABLE]
        params: list[Any] = []

        if ccaa_slug:
            condiciones.append(f"{_CCAA_SLUG_SQL} = %s")
            params.append(ccaa_slug)
        if cpv_prefijo:
            # `LIKE 'prefijo%'` y no `startswith` en Python: el filtrado tiene
            # que ocurrir en Postgres o la paginación mentiría.
            condiciones.append("l.cpv LIKE %s")
            params.append(f"{cpv_prefijo}%")

        sql = (
            f"SELECT {_SELECT_PUBLICO} FROM licitaciones l "
            f"WHERE {' AND '.join(condiciones)} "
            "ORDER BY l.fecha_publicacion DESC NULLS LAST, l.id_externo "
            "LIMIT %s OFFSET %s"
        )
        params.extend([max(1, min(limite, 200)), max(0, desplazamiento)])

        def _consultar(c: Any) -> list[dict[str, Any]]:
            return rows_to_dicts(c.execute(sql, tuple(params)))

        if conn is not None:
            return _consultar(conn)
        with connect_read() as c:
            return _consultar(c)

    def contar(
        self,
        *,
        ccaa_slug: str | None = None,
        cpv_prefijo: str | None = None,
        conn: Any | None = None,
    ) -> int:
        """Cuántos expedientes publicables hay, con los mismos filtros que ``listar``.

        Sin filtros dimensiona el sitemap; con ellos alimenta la paginación de
        un hub. El coste se asume a sabiendas: la alternativa —pedir una fila de
        más y deducir si hay siguiente— deja al hub sin poder decir cuántas hay
        en total ni enlazar a la última página, y el resultado se cachea una
        hora en el CDN, así que un ``COUNT`` por hub y hora es despreciable.

        Cuenta contratos canónicos, no filas. Es el mismo número que la landing
        publica como "expedientes publicables": antes contaba también cada
        reemisión, y con Cataluña aportando el 96,6% del corpus la cifra iba
        inflada por la republicación masiva de una sola fuente.
        """
        condiciones = [_WHERE_INDEXABLE]
        params: list[Any] = []
        if ccaa_slug:
            condiciones.append(f"{_CCAA_SLUG_SQL} = %s")
            params.append(ccaa_slug)
        if cpv_prefijo:
            condiciones.append("l.cpv LIKE %s")
            params.append(f"{cpv_prefijo}%")

        sql = f"SELECT COUNT(*) FROM licitaciones l WHERE {' AND '.join(condiciones)}"

        def _consultar(c: Any) -> int:
            fila = c.execute(sql, tuple(params)).fetchone()
            return int(fila[0]) if fila else 0

        if conn is not None:
            return _consultar(conn)
        with connect_read() as c:
            return _consultar(c)

    def ultima_incorporacion(self, *, conn: Any | None = None) -> str | None:
        """Cuándo entró el expediente publicable más reciente, o ``None``.

        Es la prueba de frescura de la superficie pública: la landing promete
        una cadencia de ingesta y hasta ahora no había en pantalla ni un dato
        que la respaldara. Devuelve ``MAX(fecha_extraccion)``, que el upsert
        refresca en cada pasada (``fecha_extraccion=excluded.fecha_extraccion``
        en ``_LIC_UPDATES``, sin ``COALESCE``), así que se mueve tanto al
        incorporar un expediente nuevo como al reingerir uno ya visto.

        Ojo con la etiqueta que lo acompañe: **no** es "última sincronización".
        Una pasada que no encuentra nada no mueve este valor, y decir lo
        contrario sería exactamente la clase de afirmación que ADR-014 prohíbe.
        Lo que afirma es lo que mide: cuándo entró el último expediente.

        La columna es ``TEXT`` con ISO 8601 UTC (``now_utc_iso``), cuyo orden
        lexicográfico coincide con el cronológico, así que ``MAX`` es correcto
        sin castear. El filtro es el mismo ``_WHERE_INDEXABLE`` que ``contar``:
        el dato tiene que hablar del corpus que se publica, no de la tabla
        entera — y una reemisión que no llega a página tampoco puede acreditar
        frescura, porque el visitante no puede abrirla.
        """
        sql = f"SELECT MAX(l.fecha_extraccion) FROM licitaciones l WHERE {_WHERE_INDEXABLE}"

        def _consultar(c: Any) -> str | None:
            fila = c.execute(sql).fetchone()
            valor = fila[0] if fila else None
            return str(valor) if valor else None

        if conn is not None:
            return _consultar(conn)
        with connect_read() as c:
            return _consultar(c)

    def hubs_ccaa(self, *, conn: Any | None = None) -> list[dict[str, Any]]:
        """Comunidades autónomas con volumen suficiente para tener página.

        El umbral no es decorativo: un hub con dos licitaciones es contenido
        delgado, y publicar veinte así arrastra al dominio entero. Las que no
        llegan no desaparecen del sitio —sus fichas siguen existiendo— pero no
        reciben página de índice propia.
        """
        sql = (
            f"SELECT {_CCAA_SLUG_SQL} AS slug, max(l.ccaa) AS nombre, COUNT(*) AS total "
            f"FROM licitaciones l WHERE {_WHERE_INDEXABLE} AND l.ccaa IS NOT NULL "
            f"GROUP BY slug HAVING COUNT(*) >= {_MIN_POR_HUB} "
            "ORDER BY total DESC"
        )

        def _consultar(c: Any) -> list[dict[str, Any]]:
            return rows_to_dicts(c.execute(sql))

        if conn is not None:
            return _consultar(conn)
        with connect_read() as c:
            return _consultar(c)

    def hubs_cpv(self, *, conn: Any | None = None) -> list[dict[str, Any]]:
        """Códigos CPV con volumen suficiente para tener página."""
        sql = (
            "SELECT l.cpv AS codigo, COUNT(*) AS total "
            f"FROM licitaciones l WHERE {_WHERE_INDEXABLE} AND l.cpv IS NOT NULL "
            f"AND l.cpv <> '' GROUP BY l.cpv HAVING COUNT(*) >= {_MIN_POR_HUB} "
            "ORDER BY total DESC"
        )

        def _consultar(c: Any) -> list[dict[str, Any]]:
            return rows_to_dicts(c.execute(sql))

        if conn is not None:
            return _consultar(conn)
        with connect_read() as c:
            return _consultar(c)

    def pagina_de_sitemap(
        self, *, desplazamiento: int, tamano: int, conn: Any | None = None
    ) -> list[dict[str, Any]]:
        """Un tramo de ids para un fichero de sitemap.

        Devuelve solo ``id_externo``, ``ccaa``, ``titulo`` y la fecha de
        actualización: es lo que hace falta para construir la URL y su
        ``lastmod``, y traer el resto sería mover megabytes por nada.

        El orden es por ``id_externo`` y no por fecha: la partición tiene que
        ser estable entre ejecuciones o un expediente saltaría de fichero cada
        vez que se republica, y el mismo tramo devolvería URLs distintas.

        La misma exigencia de estabilidad recae sobre el filtro de canónica, y
        por eso su criterio de desempate termina en ``id_externo``: elegir la
        canónica "por cualquiera de las dos" haría que la URL de un contrato
        cambiara entre regeneraciones del sitemap, que es exactamente lo que
        este orden existe para evitar.
        """
        sql = (
            "SELECT l.id_externo, l.ccaa, l.titulo, l.fecha_extraccion "
            f"FROM licitaciones l WHERE {_WHERE_INDEXABLE} "
            "ORDER BY l.id_externo LIMIT %s OFFSET %s"
        )
        params = (max(1, min(tamano, 50_000)), max(0, desplazamiento))

        def _consultar(c: Any) -> list[dict[str, Any]]:
            return rows_to_dicts(c.execute(sql, params))

        if conn is not None:
            return _consultar(conn)
        with connect_read() as c:
            return _consultar(c)
