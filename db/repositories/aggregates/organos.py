"""Órganos de contratación: totales, ranking y treemap."""

from __future__ import annotations

from typing import TypedDict

from db.database import connect_read
from db.repositories.aggregates.filtros import (
    LicitacionesFilters,
    _build_where,
)
from db.repositories.base import rows_to_dicts, typed_rows
from db.sql_fragments import (
    clave_organo_sql,
    escape_like,
    fold_expr,
    nombre_organo_sql,
)


class OrganoRankingFila(TypedDict):
    organo_contratacion: str
    count: int
    importe: float
    ccaa_mode: str | None
    organo_id: int | None
    dir3: str | None
    url_perfil: str | None


class TreemapFila(TypedDict):
    organo: str
    tipo_contrato: str
    importe: float


class OrganosMixin:
    """Órganos de contratación: totales, ranking y treemap."""

    # ── Organos ──────────────────────────────────────────────────────────
    #
    # Las tres consultas agregan por hash y nunca ordenan la tabla. Sin filtros
    # recorren las ~713k filas, y en el Supabase Micro de producción
    # (``work_mem`` de 3,5 MB) un ``COUNT(DISTINCT ...)`` o un ``mode() WITHIN
    # GROUP`` ordenaban todas esas filas en disco antes de agregar. Peor era el
    # treemap: buscaba los 30 órganos mayores y luego leía sus filas una a una
    # por ``idx_organo``, cientos de miles de lecturas sueltas, y era la
    # sentencia que moría por ``statement_timeout`` (logs de Render del
    # 2026-09-25). Agrupar primero deja unos miles de grupos en memoria, y lo
    # que se ordena después es ese resultado, no la tabla: el treemap reescrito
    # tarda 4,7 s sin filtros donde el anterior pasaba de 30.

    def _organos_where(
        self, filters: LicitacionesFilters, q: str | None
    ) -> tuple[str, list[object]]:
        """WHERE común de /organos: filtros estándar + búsqueda plegada en el nombre.

        ``q`` llega YA plegado por el servicio (``fold_text``); aquí solo se
        pliega la columna. Búsqueda separada del ``q`` genérico de
        ``_build_where`` porque este busca solo en el nombre del órgano y sin
        tildes/mayúsculas.
        """
        where, params = _build_where(filters)
        if q:
            where += f" AND {fold_expr('organo_contratacion')} LIKE %s ESCAPE '\\'"
            params.append(f"%{escape_like(q)}%")
        return where, params

    def organos_totales(
        self, filters: LicitacionesFilters, *, q_folded: str | None
    ) -> tuple[int, int, float]:
        """(filas totales, órganos únicos, importe total) del dataset filtrado."""
        where, params = self._organos_where(filters, q_folded)
        # C1.2 — el conteo de órganos únicos usa la MISMA clave que el ranking.
        # Si contara por texto crudo mientras el ranking agrupa por `organo_id`,
        # los porcentajes del ranking se calcularían contra otro denominador y
        # no sumarían 100.
        #
        # Un grupo por clave en vez de `COUNT(DISTINCT clave)`: el mismo
        # resultado sin ordenar la tabla. Las filas sin órgano forman el grupo de
        # clave NULL, que suma filas e importe y `COUNT(clave)` no cuenta como
        # órgano, igual que hacía el `DISTINCT`.
        clave = clave_organo_sql("f")
        sql = (
            "SELECT COALESCE(SUM(g.n), 0), COUNT(g.clave), COALESCE(SUM(g.importe), 0) "
            f"FROM (SELECT {clave} AS clave, COUNT(*) AS n, SUM(f.importe) AS importe "
            f"      FROM (SELECT * FROM licitaciones WHERE {where}) f "
            "      GROUP BY 1) g"
        )
        with connect_read() as c:
            row = c.execute(sql, params).fetchone()
        if row is None:
            return 0, 0, 0.0
        return int(row[0] or 0), int(row[1] or 0), float(row[2] or 0.0)

    def organos_ranking(
        self, filters: LicitacionesFilters, *, q_folded: str | None, limit: int
    ) -> list[OrganoRankingFila]:
        """Ranking (count DESC) con la CCAA modal por órgano.

        La CCAA modal replica el ``mode().iloc[0]`` de pandas: la más frecuente,
        empates a la primera por orden alfabético, NULLs fuera. Es lo que hacía
        ``mode() WITHIN GROUP (ORDER BY ccaa)``, que Postgres solo sabe calcular
        ordenando las filas de cada grupo; aquí sale del ``DISTINCT ON`` de
        ``moda``, que ordena el agregado por órgano y CCAA —unos miles de filas—
        y no la tabla.
        """
        where, params = self._organos_where(filters, q_folded)
        # C1.2 — lectura dual: se agrupa por `organo_id` cuando el maestro lo
        # resolvió y por nombre plegado cuando no. Antes se agrupaba por el
        # texto crudo, así que «Ayuntamiento de Madrid» y «AYUNTAMIENTO DE
        # MADRID» eran dos órganos con dos historiales.
        #
        # El `WHERE` va en una subconsulta y no en el `JOIN` porque
        # `_build_where` emite predicados **sin alias**, y `organos` también
        # tiene una columna `ccaa`: unirlas al mismo nivel haría ambiguo cada
        # filtro por comunidad. La subconsulta conserva el contrato del builder
        # sin tocarlo.
        #
        # `clave` y `nombre` nunca son NULL en `por_ccaa` (hay órgano), así que
        # el `JOIN` con `moda` por igualdad no pierde grupos.
        clave = clave_organo_sql("f")
        nombre = nombre_organo_sql("f", "o")
        sql = (
            "WITH por_ccaa AS ("
            f"  SELECT {clave} AS clave, {nombre} AS nombre, f.ccaa, "
            "         COUNT(*) AS n, SUM(f.importe) AS importe, "
            "         MAX(o.organo_id) AS organo_id, MAX(o.dir3) AS dir3, "
            "         MAX(o.url_perfil) AS url_perfil "
            f"  FROM (SELECT * FROM licitaciones WHERE {where}) f "
            "  LEFT JOIN organos o ON o.organo_id = f.organo_id "
            "  WHERE f.organo_contratacion IS NOT NULL "
            "  GROUP BY 1, 2, 3"
            "), moda AS ("
            "  SELECT DISTINCT ON (clave, nombre) clave, nombre, ccaa "
            "  FROM por_ccaa WHERE ccaa IS NOT NULL "
            "  ORDER BY clave, nombre, n DESC, ccaa"
            ") "
            "SELECT p.nombre AS organo_contratacion, SUM(p.n)::bigint AS count, "
            "       COALESCE(SUM(p.importe), 0) AS importe, m.ccaa AS ccaa_mode, "
            "       MAX(p.organo_id) AS organo_id, MAX(p.dir3) AS dir3, "
            "       MAX(p.url_perfil) AS url_perfil "
            "FROM por_ccaa p "
            "LEFT JOIN moda m ON m.clave = p.clave AND m.nombre = p.nombre "
            "GROUP BY p.clave, p.nombre, m.ccaa "
            "ORDER BY count DESC, p.nombre LIMIT %s"
        )
        with connect_read() as c:
            return typed_rows(OrganoRankingFila, rows_to_dicts(c.execute(sql, [*params, limit])))

    def organos_treemap(
        self, filters: LicitacionesFilters, *, q_folded: str | None, top_organos: int
    ) -> list[TreemapFila]:
        """(organo, tipo_contrato, importe) para los top-N órganos por count.

        Un solo recorrido: ``por_tipo`` agrega por órgano y tipo, y de ese
        agregado salen tanto los órganos mayores (la suma de sus grupos es su
        número de filas) como su desglose. El importe de un grupo con tipo es el
        que sumaba el filtro ``importe IS NOT NULL`` de antes —``SUM`` ya ignora
        los NULL— y ``importe > 0`` hace de ``HAVING``. El nombre desempata a los
        órganos con el mismo número de filas, que antes quedaban a merced del
        plan.
        """
        where, params = self._organos_where(filters, q_folded)
        sql = (
            "WITH por_tipo AS ("
            "  SELECT organo_contratacion, tipo_contrato, COUNT(*) AS n, "
            "         SUM(importe) AS importe "
            f"  FROM licitaciones WHERE {where} AND organo_contratacion IS NOT NULL "
            "  GROUP BY organo_contratacion, tipo_contrato"
            "), top_org AS ("
            "  SELECT organo_contratacion FROM por_tipo "
            "  GROUP BY organo_contratacion "
            "  ORDER BY SUM(n) DESC, organo_contratacion LIMIT %s"
            ") "
            "SELECT p.organo_contratacion AS organo, p.tipo_contrato, p.importe "
            "FROM por_tipo p "
            "WHERE p.organo_contratacion IN (SELECT organo_contratacion FROM top_org) "
            "  AND p.tipo_contrato IS NOT NULL AND p.importe > 0"
        )
        with connect_read() as c:
            return typed_rows(TreemapFila, rows_to_dicts(c.execute(sql, [*params, top_organos])))
