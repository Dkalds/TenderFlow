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
las que llevan ``LIMIT`` usan el anti-join ``_WHERE_INDEXABLE`` y las que
agregan la tabla entera usan ``_canonicas_from`` (ver la nota que las compara,
con sus tiempos medidos). Las dos parten de ``_BASE_WHERE`` y del mismo orden
canónico, y ``tests/test_publico_canonicas_equivalencia.py`` comprueba que
seleccionan el mismo conjunto — porque si discreparan, ``contar`` diría un
número que el hub no puede paginar y Search Console lo reportaría como error de
cobertura sin decir por qué.
"""

from __future__ import annotations

from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from db.sql_fragments import (
    FOLD_DST,
    FOLD_SRC,
    clave_canonica_agrupable_sql,
    exclude_duplicados_sql,
    fila_canonica_sql,
    orden_canonico_sql,
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


# ── Dos formas de decir lo mismo, y cuándo usa cada una ───────────────────
# `_WHERE_INDEXABLE` (anti-join) y `_CANONICAS_FROM` (agrupación) seleccionan
# EXACTAMENTE el mismo conjunto de filas. Conviven porque su coste se invierte
# según haya o no un `LIMIT` que corte pronto:
#
#   · Anti-join: un sondeo indexado por fila candidata. Con `LIMIT 10000` el
#     plan para en cuanto junta las filas pedidas — 5,9 s para un tramo del
#     sitemap. Sin `LIMIT` son ~695k sondeos: ~200 s, muy por encima del
#     `statement_timeout` de 30 s del rol de la API.
#   · Agrupación: una pasada, un `DISTINCT ON` sobre la clave. No se beneficia
#     de un `LIMIT` pequeño, pero recorre la tabla una sola vez — 9,1 s con el
#     `work_mem` real de producción (3500 kB, plan paralelo con dos workers).
#
# Regla: si la consulta lleva `LIMIT`, anti-join; si agrega la tabla entera,
# agrupación. Se desplegó lo contrario en #226 y tumbó la superficie pública
# entera durante horas (500 por `QueryCanceled`), que es la razón por la que
# esta nota existe y por la que las cifras de arriba están medidas y no
# estimadas.
_CLAVE_AGRUPABLE = clave_canonica_agrupable_sql("l")
_ORDEN_CANONICO = orden_canonico_sql("l")


def _canonicas_from(columnas: str) -> str:
    """Subconsulta con **una fila por contrato canónico** y las columnas pedidas.

    ``columnas`` se proyecta desde el alias ``l``; el resultado se expone como
    ``c`` para que el llamante filtre y agregue sobre él.

    **Dentro de esta subconsulta sólo va la publicabilidad, nunca los filtros
    del llamante.** En el anti-join la canonicidad se decide sobre el corpus
    publicable completo y el filtro de comunidad o CPV se conjuga después; si
    aquí se metiera dentro, la fila canónica se elegiría entre las candidatas
    que el filtro deja pasar y no entre todas. Efecto concreto: un contrato cuya
    fila canónica está en otra comunidad aparecería en el hub por su fila
    gemela, que es justamente el duplicado que este filtro existe para evitar.
    Los filtros se aplican **fuera**, sobre ``c``.
    """
    return (
        f"(SELECT DISTINCT ON ({_CLAVE_AGRUPABLE}) {columnas} "
        f"FROM licitaciones l WHERE {_BASE_WHERE} "
        f"ORDER BY {_CLAVE_AGRUPABLE}, {_ORDEN_CANONICO}) AS c"
    )


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
        condiciones: list[str] = []
        params: list[Any] = []
        if ccaa_slug:
            condiciones.append(f"{_ccaa_slug_sql('c')} = %s")
            params.append(ccaa_slug)
        if cpv_prefijo:
            condiciones.append("c.cpv LIKE %s")
            params.append(f"{cpv_prefijo}%")

        # Agrupación y no anti-join: este COUNT no tiene `LIMIT` que corte, así
        # que recorre la tabla entera. Ver la nota de `_canonicas_from`.
        where = f" WHERE {' AND '.join(condiciones)}" if condiciones else ""
        sql = f"SELECT COUNT(*) FROM {_canonicas_from('l.ccaa, l.cpv')}{where}"

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
        # Agrupación y no anti-join: un MAX sobre la tabla entera no tiene
        # `LIMIT` que corte. Ver la nota de `_canonicas_from`.
        sql = f"SELECT MAX(c.fecha_extraccion) FROM {_canonicas_from('l.fecha_extraccion')}"

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
        # Agrupación y no anti-join: agrega la tabla entera sin `LIMIT` que
        # corte. Ver la nota de `_canonicas_from`. El `ccaa IS NOT NULL` va
        # FUERA de la subconsulta, para que la canónica se elija entre todas
        # las gemelas y no sólo entre las que declaran comunidad.
        sql = (
            f"SELECT {_ccaa_slug_sql('c')} AS slug, max(c.ccaa) AS nombre, COUNT(*) AS total "
            f"FROM {_canonicas_from('l.ccaa')} WHERE c.ccaa IS NOT NULL "
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
        # Agrupación y no anti-join: ver la nota de `_canonicas_from`.
        sql = (
            "SELECT c.cpv AS codigo, COUNT(*) AS total "
            f"FROM {_canonicas_from('l.cpv')} WHERE c.cpv IS NOT NULL "
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
