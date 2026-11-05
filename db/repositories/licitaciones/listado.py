"""Listado de ``licitaciones``: paginado por offset, por cursor y rama FTS."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, and_, func, or_, select

from db.database import connect_read, fts_available
from db.models import _DIALECT, compile_query, licitaciones
from db.repositories.base import csv_values, rows_to_dicts, typed_rows
from db.repositories.licitaciones.filas import LicitacionResumenRow
from db.repositories.licitaciones.filtros import (
    _DATE_RE,
    OBJETO_ETIQUETA_EXPEDIENTE,
    FiltrosMixin,
    _columnas_resumen,
    _columnas_resumen_sql,
    _dia_siguiente,
    _etiqueta_requerida,
    _normaliza_codigo,
    _nucleo,
    _orden,
    _orden_cursor,
    _tipos_de_contrato,
)
from db.sql_fragments import (
    FOLD_TABLE,
    columna_nucleo_sql,
    escape_like,
    exclude_duplicados_presentacion_sql,
    fecha_valida_sql,
    fold_expr,
    tecnologia_en_csv_sql,
    universo_producto_sql,
)
from shared.dto import FiltrosLicitacion
from shared.estados import ESTADOS_CERRADOS, abierta_sql, abierta_sql_marcadores


class ListadoMixin(FiltrosMixin):
    """Listado paginado (offset y cursor) y su recuento."""

    def list_paginated(
        self,
        filtros: FiltrosLicitacion | None = None,
        *,
        limit: int = 50,
        offset: int = 0,
        sort: str | None = None,
        with_total: bool = True,
    ) -> tuple[list[LicitacionResumenRow], int]:
        """Devuelve (items, total).  Si ``with_total=False`` total==-1.

        Los filtros llegan juntos en ``filtros`` (:class:`shared.dto.FiltrosLicitacion`,
        ``None`` = sin filtros); aquí solo viajan sueltos la página y el orden.

        ``solo_abiertas`` descarta los estados terminales de
        :data:`shared.estados.ESTADOS_CERRADOS` (resuelta, adjudicada,
        anulada). Es el filtro que necesita cualquier superficie de
        oportunidad — el Radar — para no proponer expedientes cerrados.

        ``cierre_desde``/``cierre_hasta`` acotan ``fecha_limite`` (ver
        :meth:`_base_filters`). Una fila sin plazo publicado queda fuera en
        cuanto se pide cualquiera de las dos cotas: NULL no cumple el guard
        ISO, igual que en los contadores de ``/analytics/resumen/hoy``.
        """
        filtros = filtros or FiltrosLicitacion()
        order = _orden(sort)
        clauses = self._base_filters(filtros)

        # Usar FTS5 para búsquedas de texto si disponible
        if filtros.q and fts_available():
            return self._list_fts(
                filtros, limit=limit, offset=offset, order=order, with_total=with_total
            )

        # Query SA Core
        base: Select[Any] = select(*_columnas_resumen()).select_from(licitaciones)
        if clauses:
            base = base.where(and_(*clauses))

        count_stmt = select(func.count()).select_from(base.subquery())
        data_stmt = base.order_by(order).limit(limit).offset(offset)

        count_sql, count_params = compile_query(count_stmt)
        data_sql, data_params = compile_query(data_stmt)

        with connect_read() as c:
            total = -1
            if with_total:
                row = c.execute(count_sql, count_params).fetchone()
                total = int(row[0]) if row else 0
            items = typed_rows(
                LicitacionResumenRow, rows_to_dicts(c.execute(data_sql, data_params))
            )

        return items, total

    def _list_fts(
        self,
        filtros: FiltrosLicitacion,
        *,
        limit: int,
        offset: int,
        order: Any,
        with_total: bool,
    ) -> tuple[list[LicitacionResumenRow], int]:
        """Búsqueda FTS5: usa SQL directo porque FTS MATCH no tiene soporte SA.

        Solo se llega con ``filtros.q`` puesto (lo decide ``list_paginated``).
        """
        # Núcleo tipado (T2): las mismas columnas que `_base_filters` elige vía
        # `_nucleo`, en su forma de texto. Apagado son `l.fecha_publicacion`,
        # `l.fecha_limite` y `l.importe`, como siempre.
        fpub = columna_nucleo_sql("fecha_publicacion", "l")
        flim = columna_nucleo_sql("fecha_limite", "l")
        imp = columna_nucleo_sql("importe", "l")
        extra_conditions: list[str] = [
            universo_producto_sql("l"),
            # Misma regla de presentación que `_base_filters` (ADR-026 D23): la
            # búsqueda de texto es otro camino al mismo listado.
            exclude_duplicados_presentacion_sql("l.id_externo"),
        ]
        extra_params: list[object] = []
        # `csv_values` y no el valor crudo: la rama SA Core acepta multi-valor
        # (`?estado=A,B`) y ésta comparaba la cadena entera, de modo que el
        # mismo filtro devolvía cero al escribir texto en la caja.
        if estados := csv_values(filtros.estado):
            marcadores = ", ".join(["%s"] * len(estados))
            extra_conditions.append(f"l.estado IN ({marcadores})")
            extra_params.extend(estados)
        if filtros.solo_abiertas:
            # Mismo criterio y ahora también misma grafía que la rama SA Core y
            # que los agregados: el predicado lo emite `shared.estados`. Antes
            # eran tres escrituras equivalentes del mismo juicio, y equivalente
            # no protege de que sólo una cambie.
            extra_conditions.append(abierta_sql_marcadores("l.estado", n=len(ESTADOS_CERRADOS)))
            extra_params.extend(ESTADOS_CERRADOS)
        if ccaas := csv_values(filtros.ccaa):
            marcadores = ", ".join(["%s"] * len(ccaas))
            extra_conditions.append(f"l.ccaa IN ({marcadores})")
            extra_params.extend(ccaas)
        tecnologias = csv_values(filtros.tecnologia)
        if tecnologias:
            # Igualdad no: `tecnologia` guarda un CSV por fila, así que buscar
            # SAP escondía los expedientes que además llevan otra. La rama SA
            # Core ya explotaba el CSV; ésta comparaba por igualdad, de modo que
            # escribir texto en la caja cambiaba el universo del filtro.
            extra_conditions.append(tecnologia_en_csv_sql("l.tecnologia", n=len(tecnologias)))
            extra_params.extend(tecnologias)

        # Tecnología **predicha** (el modelo, no la etiqueta). No llegaba hasta
        # aquí: la rama SA Core la aplicaba y ésta ni siquiera recibía el
        # parámetro, así que escribir en la caja de búsqueda desactivaba el
        # filtro en silencio y devolvía expedientes de cualquier tecnología.
        # Misma semántica que `_base_filters`: con umbral, EXISTS sobre los
        # scores; sin él, principal o pertenencia al CSV de predichas.
        if filtros.tecnologia_predicha:
            if filtros.min_proba_tech is not None:
                extra_conditions.append(
                    "EXISTS (SELECT 1 FROM licitacion_tecnologia_score s "
                    "WHERE s.licitacion_id = l.id_externo AND s.tecnologia = %s "
                    "  AND s.probabilidad >= %s)"
                )
                extra_params.extend([filtros.tecnologia_predicha, float(filtros.min_proba_tech)])
            else:
                extra_conditions.append(
                    "(l.ml_tech_principal = %s OR l.ml_tecnologias = %s "
                    " OR l.ml_tecnologias LIKE %s OR l.ml_tecnologias LIKE %s "
                    " OR l.ml_tecnologias LIKE %s)"
                )
                t = escape_like(filtros.tecnologia_predicha)
                extra_params.extend(
                    [
                        filtros.tecnologia_predicha,
                        filtros.tecnologia_predicha,
                        f"{t},%",
                        f"%,{t},%",
                        f"%,{t}",
                    ]
                )

        if filtros.fecha_desde and _DATE_RE.match(filtros.fecha_desde):
            extra_conditions.append(f"{fpub} >= %s")
            extra_params.append(filtros.fecha_desde)
        if filtros.fecha_hasta and _DATE_RE.match(filtros.fecha_hasta):
            extra_conditions.append(f"{fpub} <= %s")
            extra_params.append(filtros.fecha_hasta)
        # La ventana de cierre también aquí: si esta rama se saltara el recorte,
        # escribir en la búsqueda global convertiría en silencio un listado de
        # «vencen esta semana» en el catálogo entero que casa con el texto.
        cierre_desde_ok = bool(filtros.cierre_desde and _DATE_RE.match(filtros.cierre_desde))
        hasta_exclusivo = (
            _dia_siguiente(filtros.cierre_hasta)
            if filtros.cierre_hasta and _DATE_RE.match(filtros.cierre_hasta)
            else None
        )
        if cierre_desde_ok or hasta_exclusivo:
            extra_conditions.append(fecha_valida_sql("fecha_limite", "l"))
        if cierre_desde_ok:
            extra_conditions.append(f"{flim} >= %s")
            extra_params.append(filtros.cierre_desde)
        if hasta_exclusivo:
            extra_conditions.append(f"{flim} < %s")
            extra_params.append(hasta_exclusivo)

        # ── F1.1 en la rama FTS ──────────────────────────────────────────
        #
        # Esta rama vuelve a escribir en SQL crudo lo que la rama SA Core
        # expresa con `_base_filters`, porque `MATCH` no tiene equivalente en
        # SA. La duplicación es conocida y peligrosa —así fue como `tecnologia`
        # acabó comparándose por igualdad aquí y por CSV allí—, y por eso el
        # test de paridad de F1.1 compara el `COUNT(*)` de las dos ramas con
        # los mismos filtros: si una se queda atrás, falla.
        if filtros.importe_min is not None:
            extra_conditions.append(f"{imp} >= %s")
            extra_params.append(float(filtros.importe_min))
        if filtros.importe_max is not None:
            extra_conditions.append(f"{imp} <= %s")
            extra_params.append(float(filtros.importe_max))

        cpvs = csv_values(filtros.cpv)
        if cpvs:
            extra_conditions.append("(" + " OR ".join(["l.cpv LIKE %s" for _ in cpvs]) + ")")
            extra_params.extend(f"{escape_like(c)}%" for c in cpvs)

        organos = csv_values(filtros.organo)
        if organos:
            plegado = fold_expr("l.organo_contratacion")
            extra_conditions.append(
                "(" + " OR ".join([f"{plegado} LIKE %s" for _ in organos]) + ")"
            )
            extra_params.extend(
                f"%{escape_like(o.translate(FOLD_TABLE).lower())}%" for o in organos
            )

        provincias = csv_values(filtros.provincia)
        if provincias:
            marcadores = ", ".join(["%s"] * len(provincias))
            extra_conditions.append(f"l.provincia IN ({marcadores})")
            extra_params.extend(provincias)

        for columna, valores in (
            ("l.procedimiento", csv_values(filtros.procedimiento)),
            ("l.tramitacion", csv_values(filtros.tramitacion)),
            ("l.tipo_contrato", csv_values(filtros.tipo_contrato)),
        ):
            textos: list[str] = []
            if columna == "l.tipo_contrato":
                codigos, textos = _tipos_de_contrato(valores)
            else:
                codigos = sorted({_normaliza_codigo(v) for v in valores if v.strip()})
            if codigos:
                marcadores = ", ".join(["%s"] * len(codigos))
                normalizada = f"COALESCE(NULLIF(ltrim(trim({columna}), '0'), ''), '0')"
                condicion = f"{normalizada} IN ({marcadores})"
                extra_params.extend(codigos)
                if textos:
                    # El texto con que la fuente escribe el mismo tipo («Serveis»).
                    marcadores = ", ".join(["%s"] * len(textos))
                    condicion = f"({condicion} OR {fold_expr(columna)} IN ({marcadores}))"
                    extra_params.extend(textos)
                extra_conditions.append(condicion)

        if filtros.dias_restantes_max is not None:
            tope = (
                (datetime.now(UTC) + timedelta(days=int(filtros.dias_restantes_max)))
                .date()
                .isoformat()
            )
            extra_conditions.append(fecha_valida_sql("fecha_limite", "l"))
            extra_conditions.append(f"{flim} >= %s")
            extra_params.append(datetime.now(UTC).date().isoformat())
            extra_conditions.append(f"{flim} < %s")
            extra_params.append(_dia_siguiente(tope))
            extra_conditions.append(abierta_sql("l.estado"))

        # Mismo `EXISTS` que `_base_filters`: sin él, escribir en la caja de
        # búsqueda soltaría la etiqueta y devolvería el corpus que casa con el
        # texto.
        if etiqueta := _etiqueta_requerida(filtros.etiqueta_id, filtros.etiqueta_organization_id):
            extra_conditions.append(
                "EXISTS (SELECT 1 FROM etiquetas_aplicadas ea "
                "WHERE ea.organization_id = %s AND ea.etiqueta_id = %s "
                "AND ea.objeto_tipo = %s AND ea.objeto_id = l.id_externo)"
            )
            extra_params.extend([*etiqueta, OBJETO_ETIQUETA_EXPEDIENTE])

        # Compilar order clause a string para insertar en FTS SQL
        compiled_order = str(order.compile(dialect=_DIALECT))
        # SA prefija la tabla: "licitaciones.fecha_publicacion DESC" → quitar prefijo
        compiled_order = compiled_order.replace("licitaciones.", "l.")

        extra_where = " AND ".join(extra_conditions)
        col_list = _columnas_resumen_sql("l")
        match_clause = "l.search_vector @@ websearch_to_tsquery('spanish', %s)"
        base_sql = f"SELECT {col_list} FROM licitaciones l WHERE {match_clause} AND {extra_where}"
        count_sql = f"SELECT COUNT(*) FROM licitaciones l WHERE {match_clause} AND {extra_where}"

        with connect_read() as c:
            total = -1
            if with_total:
                count_row = c.execute(count_sql, [filtros.q, *extra_params]).fetchone()
                total = int(count_row[0]) if count_row else 0
            items = typed_rows(
                LicitacionResumenRow,
                rows_to_dicts(
                    c.execute(
                        base_sql + f" ORDER BY {compiled_order} LIMIT %s OFFSET %s",
                        [filtros.q, *extra_params, limit, offset],
                    )
                ),
            )
        return items, total

    def list_cursor(
        self,
        filtros: FiltrosLicitacion | None = None,
        *,
        cursor_fecha: str | None = None,
        cursor_id: str | None = None,
        limit: int = 100,
        sort: str | None = None,
        cursor_orden: tuple[str | float | None, str] | None = None,
    ) -> list[LicitacionResumenRow]:
        """Paginación por cursor (fecha_publicacion, id_externo) DESC.

        ``sort`` admite los mismos seis valores que el listado por offset
        (:data:`SORTS_CURSOR`). Sin él —o con ``fecha_publicacion``, que es el
        mismo orden— el camino es el de siempre y el cursor es
        ``(cursor_fecha, cursor_id)``. Con otro orden la clave es
        ``(columna, id_externo)`` y el cursor llega en ``cursor_orden``: ver
        :meth:`_keyset_ordenado`. Es lo que deja al listado de /detalle pasar
        del offset (en retirada, RFC 2026-09-06) al cursor sin perder la
        ordenación por importe o por título.

        Los filtros salen de :meth:`_base_filters` con el mismo
        :class:`shared.dto.FiltrosLicitacion` que el listado por offset. Antes esta función tenía su propio par de cláusulas
        —``tecnologia`` por **igualdad**, cuando la columna guarda un CSV— así
        que el endpoint «recomendado para datasets grandes» filtraba distinto
        que el que dice sustituir: pedir SAP aquí escondía los expedientes que
        además llevan otra tecnología. Compartir el constructor es lo que hace
        cierto el test de paridad de F1.1.
        """
        clauses = self._base_filters(filtros)

        if sort and sort != "fecha_publicacion":
            return self._keyset_ordenado(clauses, sort=sort, cursor=cursor_orden, limit=limit)

        # Clave del cursor sobre la columna del núcleo vigente (T2). El valor
        # del cursor sigue siendo el TEXTO de la última fila —es lo que viaja
        # en el token—; con la sombra, Postgres lo interpreta como
        # `timestamptz` al compararlo, así que la clave (instante, id) ordena
        # igual siempre que el texto guardado sea el mismo instante.
        fecha = _nucleo("fecha_publicacion")
        if cursor_fecha is not None and cursor_id is not None:
            clauses.append(
                or_(
                    fecha < cursor_fecha,
                    and_(
                        fecha == cursor_fecha,
                        licitaciones.c.id_externo < cursor_id,
                    ),
                )
            )

        stmt = (
            select(*_columnas_resumen())
            .where(and_(*clauses))
            .order_by(
                fecha.desc(),
                licitaciones.c.id_externo.desc(),
            )
            .limit(limit + 1)
        )
        sql, params = compile_query(stmt)
        with connect_read() as c:
            return typed_rows(LicitacionResumenRow, rows_to_dicts(c.execute(sql, params)))

    @staticmethod
    def _keyset_ordenado(
        clauses: list[Any],
        *,
        sort: str,
        cursor: tuple[str | float | None, str] | None,
        limit: int,
    ) -> list[LicitacionResumenRow]:
        """Keyset ``(columna, id_externo)`` para los órdenes distintos del de fecha.

        **Nulos al final en los dos sentidos** (``NULLS LAST``). El listado por
        offset los dejaba donde Postgres quiere —primero en ``DESC`` en importe—,
        lo que abría «mayor importe» con una página de expedientes sin importe.
        Y el keyset lo necesita: con los nulos al final, el cursor tiene dos
        tramos bien definidos —con valor y la cola de nulos— y la cláusula de
        «después de» se escribe sin ambigüedad:

        - cursor con valor ``v``: ``col ⋚ v`` o (``col = v`` e ``id ⋚ id₀``) o
          ``col IS NULL`` (la cola entera va después);
        - cursor en la cola (``v`` nulo): ``col IS NULL`` e ``id ⋚ id₀``.

        El desempate por ``id_externo`` va en el mismo sentido que la columna,
        y hace el orden total: sin él, dos importes iguales podían aparecer en
        dos páginas o en ninguna.
        """
        columna, descendente = _orden_cursor(sort)
        id_col = licitaciones.c.id_externo
        if cursor is not None:
            valor, id_previo = cursor
            id_despues = id_col < id_previo if descendente else id_col > id_previo
            if valor is None:
                clauses = [*clauses, and_(columna.is_(None), id_despues)]
            else:
                col_despues = columna < valor if descendente else columna > valor
                clauses = [
                    *clauses,
                    or_(col_despues, and_(columna == valor, id_despues), columna.is_(None)),
                ]
        orden_col = columna.desc() if descendente else columna.asc()
        orden_id = id_col.desc() if descendente else id_col.asc()
        stmt = (
            select(*_columnas_resumen())
            .where(and_(*clauses))
            .order_by(orden_col.nulls_last(), orden_id)
            .limit(limit + 1)
        )
        sql, params = compile_query(stmt)
        with connect_read() as c:
            return typed_rows(LicitacionResumenRow, rows_to_dicts(c.execute(sql, params)))

    def count_cursor(self, filtros: FiltrosLicitacion | None = None) -> int:
        """``COUNT(*)`` del universo que recorre :meth:`list_cursor` con esos filtros.

        Mismo constructor de cláusulas (:meth:`_base_filters`), así que el total
        y las páginas no pueden discrepar. Lo pide el listado por cursor sólo
        con ``with_total=true``: el cursor existe para no pagar este conteo en
        cada página, y quien lo quiere lo pide una vez.
        """
        clauses = self._base_filters(filtros)
        stmt = select(func.count()).select_from(licitaciones)
        if clauses:
            stmt = stmt.where(and_(*clauses))
        sql, params = compile_query(stmt)
        with connect_read() as c:
            row = c.execute(sql, params).fetchone()
        return int(row[0]) if row else 0
