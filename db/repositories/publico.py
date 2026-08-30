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
colapsan las reemisiones del mismo contrato con la MISMA regla, escrita una
sola vez. Lo que cambia entre ellas es la forma de aplicarla, no el criterio:
todas leen de la vista materializada ``licitaciones_canonicas`` (revisión
``v94``), que es donde vive la definición de qué contrato se publica. Antes cada
una aplicaba el filtro por su cuenta y el coste era insostenible; ver la nota
sobre la vista más abajo, con los tiempos medidos. Que las seis lean del MISMO
sitio es lo que impide que discrepen: si ``contar`` dijera un número que el hub
no puede paginar, Search Console lo reportaría como error de cobertura sin decir
por qué.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read
from db.repositories.base import rows_to_dicts
from db.sql_fragments import (
    FOLD_DST,
    FOLD_SRC,
    exclude_duplicados_sql,
    fila_canonica_sql,
)

__all__ = [
    "EVENTO_REFRESCO_CANONICAS",
    "PublicoRepository",
    "estado_refresco_canonicas",
    "refrescar_vista_canonicas",
]


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
# Coste: ver `fila_canonica_sql`. Resumen — anti-join sobre las ~586k filas
# publicables, apoyado en `idx_lic_clave_canonica` (revisión v92), y el listado
# ya no puede resolver su `ORDER BY ... LIMIT` por índice. Lo paga una
# revalidación ISR cacheada una hora, no cada visita.
#
# Ese índice no es una optimización opcional: #226 desplegó estas consultas sin
# él y las seis superficies devolvieron 500 por `statement_timeout` hasta que
# v92 lo creó. Si alguien lo retira, esto se cae otra vez.
_CANONICA_SQL = fila_canonica_sql(alias="l", gemelo="l2", filtro_gemelo=_publicable_sql("l2"))

#: Filtro de las seis superficies indexables. `_BASE_WHERE` es un superconjunto
#: suyo, nunca al revés: una URL del sitemap siempre tiene ficha.
_WHERE_INDEXABLE = f"{_BASE_WHERE} AND {_CANONICA_SQL}"


# ── De dónde salen las canónicas: la vista materializada ──────────────────
# Las SEIS superficies indexables leen de `licitaciones_canonicas` (revisión
# v94), no de `licitaciones` con el filtro puesto. Los dos intentos anteriores
# están documentados aquí porque explican por qué hizo falta:
#
#   · #226 metió el anti-join (`_CANONICA_SQL`) en las seis. Sin índice son
#     ~200 s y tumbó la superficie pública entera durante horas.
#   · v92 puso el índice, que arregla las consultas CON `LIMIT` —el plan corta
#     pronto— y deja los agregados entre 9 y 30 s según si el planificador
#     consigue un worker paralelo. La instancia tiene `max_worker_processes = 6`,
#     así que no lo consigue siempre: medido en producción, los mismos endpoints
#     alternaban entre 200 y 500. Un 500 intermitente en la superficie que
#     rastrea Googlebot es peor que uno limpio, porque no es diagnosticable.
#
# Materializar mueve ese coste a una vez por pasada del pipeline. Y van las
# seis, no sólo las cuatro que fallaban: si `listar` leyera en vivo y `contar`
# la vista, un expediente recién ingerido saldría en el listado sin estar
# contado y el hub paginaría hacia una página vacía — el error de cobertura que
# este módulo lleva advirtiendo desde el principio. La frescura tiene que ser
# uniforme, aunque sea menor.
#
# `_CANONICA_SQL` y `_WHERE_INDEXABLE` se conservan: son la DEFINICIÓN de qué es
# canónico —la gemela de lo que materializa v94— y lo que compara
# `tests/test_mv_canonicas_definicion.py`. Ya no los ejecuta ninguna consulta.
#
# Contrato de frescura, que hay que respetar al tocar esto: la vista va tan
# fresca como su último `REFRESH`, al final de la pasada de ingesta (cada 4 h).
# "Al final" es literal desde el 2026-08-30 y hubo que arreglarlo para que lo
# fuera: `scrape-daily.yml` ejecutaba la secuencia canónica entera —este
# refresco incluido— y solo entonces lanzaba TED, Galicia, Euskadi, PSCP,
# TACRC y adjudicaciones vigiladas, así que cinco de las siete fuentes
# aparecían aquí con un ciclo de retraso. Hoy el workflow parte la pasada en
# `--fase ingesta` y `--fase cierre` y el refresco corre en la segunda. Si
# alguien vuelve a juntarlas, esta frase deja de ser cierta.
# `ficha` NO lee de aquí —no aplica el filtro de canónica, asimetría deliberada
# ya documentada— así que un expediente nuevo tiene página desde el primer
# momento; lo que tarda en aparecer es en los listados y en los recuentos.
VISTA_CANONICAS = "licitaciones_canonicas"


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
def _ccaa_slug_sql(alias: str = "l") -> str:
    """El slug, escrito para un alias concreto.

    Parametrizado por alias porque los agregados lo aplican sobre la subconsulta
    de canónicas (``c``) y el listado sobre la tabla (``l``). Una constante con
    ``l`` dentro obligaría a duplicar la expresión, que es exactamente cómo se
    empieza a divergir.
    """
    return (
        "trim(both '-' from regexp_replace("
        f"lower(translate(coalesce({alias}.ccaa, ''), '{FOLD_SRC}', '{FOLD_DST}')), "
        "'[^a-z0-9]+', '-', 'g'))"
    )


_CCAA_SLUG_SQL = _ccaa_slug_sql("l")


def refrescar_vista_canonicas(*, conn: Any | None = None) -> int:
    """Recalcula ``licitaciones_canonicas`` y devuelve cuántas filas quedaron.

    Lo llama el paso ``aggregates_precompute`` del pipeline, al final de cada
    pasada de ingesta. Es lo que convierte la vista en un dato vivo: sin este
    refresco la superficie pública se congelaría en el corpus del día del
    despliegue, y —peor— lo haría en silencio, sirviendo cifras coherentes entre
    sí pero viejas.

    ``CONCURRENTLY`` no es opcional. Un ``REFRESH`` normal toma un
    ``AccessExclusiveLock`` sobre la vista: las seis superficies públicas se
    quedarían esperando los ~10 s que tarda en reconstruirse, cada cuatro horas.
    Con ``CONCURRENTLY`` las lecturas siguen sirviendo la versión anterior
    mientras se construye la nueva, que es lo que hace aceptable refrescar sobre
    una base viva. El precio es que exige el índice único de la revisión ``v94``
    y que tarda algo más, porque construye y luego difunde.

    El conteo posterior no es decorativo: es lo que permite que el job registre
    el tamaño del corpus publicable en cada pasada y que una caída brusca sea
    visible. Un refresco que deja la vista vacía —porque alguien endureció el
    umbral de sustancia sin querer— es exactamente la clase de fallo que no
    levanta ninguna excepción.
    """

    def _refrescar(c: Any) -> int:
        c.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {VISTA_CANONICAS}")
        fila = c.execute(f"SELECT COUNT(*) FROM {VISTA_CANONICAS}").fetchone()
        return int(fila[0]) if fila else 0

    if conn is not None:
        return _refrescar(conn)
    with connect() as c:
        return _refrescar(c)


#: Evento con el que ``scheduler/aggregates_precompute.py`` deja constancia de
#: cada refresco. Vive aquí, junto a la vista que describe, porque es su
#: contrato: quien renombre uno tiene el otro delante.
EVENTO_REFRESCO_CANONICAS = "mv_canonicas_refresh"


def estado_refresco_canonicas(*, conn: Any | None = None, historico: int = 2) -> dict[str, Any]:
    """Con qué frescura y qué tamaño se sirve hoy la superficie pública.

    Devuelve ``{"con_datos": bool, "eventos": [(ts, valor), …]}``, del más
    reciente al más antiguo. Lo consume ``scheduler/healthcheck.py``.

    Postgres no registra cuándo se refrescó una vista materializada, así que la
    frescura se lee del rastro que deja el job en ``ops_events``. Esa es toda la
    señal que hay: los counters de Prometheus mueren con el proceso efímero de
    Actions, y comparar la vista contra la tabla exigiría repetir el anti-join
    que la vista existe precisamente para no pagar.

    ``con_datos`` acompaña a los eventos porque sin él no se puede interpretar
    su ausencia: una vista vacía sin refrescos es una base sin corpus, y una
    vista llena sin refrescos es el job caído. Se resuelve con ``EXISTS`` y no
    con ``COUNT(*)`` — la pregunta es binaria y no hay motivo para recorrer
    400.000 filas para responderla.
    """

    def _consultar(c: Any) -> dict[str, Any]:
        con_datos = bool(
            c.execute(f"SELECT EXISTS (SELECT 1 FROM {VISTA_CANONICAS})").fetchone()[0]
        )
        eventos = c.execute(
            "SELECT ts, value FROM ops_events WHERE event_type = %s ORDER BY ts DESC LIMIT %s",
            (EVENTO_REFRESCO_CANONICAS, historico),
        ).fetchall()
        return {"con_datos": con_datos, "eventos": [(r[0], r[1]) for r in eventos]}

    if conn is not None:
        return _consultar(conn)
    with connect() as c:
        return _consultar(c)


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
        condiciones: list[str] = []
        params: list[Any] = []

        if ccaa_slug:
            condiciones.append(f"{_ccaa_slug_sql('c')} = %s")
            params.append(ccaa_slug)
        if cpv_prefijo:
            # `LIKE 'prefijo%'` y no `startswith` en Python: el filtrado tiene
            # que ocurrir en Postgres o la paginación mentiría.
            condiciones.append("c.cpv LIKE %s")
            params.append(f"{cpv_prefijo}%")

        # La vista decide QUÉ filas se publican y `licitaciones` aporta el resto
        # de columnas. Los filtros y el orden van sobre `c` —no sobre `l`— para
        # que el listado y `contar` vean literalmente el mismo conjunto: si uno
        # filtrara por la tabla y el otro por la vista, un refresco a medias los
        # haría discrepar y el hub paginaría hacia páginas vacías.
        where = f" WHERE {' AND '.join(condiciones)}" if condiciones else ""
        sql = (
            f"SELECT {_SELECT_PUBLICO} FROM {VISTA_CANONICAS} c "
            f"JOIN licitaciones l ON l.id_externo = c.id_externo{where} "
            "ORDER BY c.fecha_publicacion DESC NULLS LAST, c.id_externo "
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
        condiciones: list[str] = []
        params: list[Any] = []
        if ccaa_slug:
            condiciones.append(f"{_ccaa_slug_sql('c')} = %s")
            params.append(ccaa_slug)
        if cpv_prefijo:
            condiciones.append("c.cpv LIKE %s")
            params.append(f"{cpv_prefijo}%")

        where = f" WHERE {' AND '.join(condiciones)}" if condiciones else ""
        sql = f"SELECT COUNT(*) FROM {VISTA_CANONICAS} c{where}"

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
        sin castear. Se apoya en el mismo conjunto canónico que ``contar``:
        el dato tiene que hablar del corpus que se publica, no de la tabla
        entera — y una reemisión que no llega a página tampoco puede acreditar
        frescura, porque el visitante no puede abrirla.
        """
        sql = f"SELECT MAX(c.fecha_extraccion) FROM {VISTA_CANONICAS} c"

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
            f"SELECT {_ccaa_slug_sql('c')} AS slug, max(c.ccaa) AS nombre, COUNT(*) AS total "
            f"FROM {VISTA_CANONICAS} c WHERE c.ccaa IS NOT NULL "
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
            "SELECT c.cpv AS codigo, COUNT(*) AS total "
            f"FROM {VISTA_CANONICAS} c WHERE c.cpv IS NOT NULL "
            f"AND c.cpv <> '' GROUP BY c.cpv HAVING COUNT(*) >= {_MIN_POR_HUB} "
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
        # No toca `licitaciones`: la vista ya lleva las cuatro columnas que el
        # sitemap necesita, y su índice único sobre `id_externo` resuelve este
        # `ORDER BY ... LIMIT/OFFSET` directamente.
        sql = (
            "SELECT c.id_externo, c.ccaa, c.titulo, c.fecha_extraccion "
            f"FROM {VISTA_CANONICAS} c "
            "ORDER BY c.id_externo LIMIT %s OFFSET %s"
        )
        params = (max(1, min(tamano, 50_000)), max(0, desplazamiento))

        def _consultar(c: Any) -> list[dict[str, Any]]:
            return rows_to_dicts(c.execute(sql, params))

        if conn is not None:
            return _consultar(conn)
        with connect_read() as c:
            return _consultar(c)
