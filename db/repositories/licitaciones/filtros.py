"""Filtros, órdenes y columnas del listado de ``licitaciones``.

:class:`FiltrosMixin` es el único sitio que traduce
:class:`shared.dto.FiltrosLicitacion` a SQL Core; los helpers de columna y de
orden los comparten el listado, la búsqueda y la bandeja «Próximas».
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

from sqlalchemy import Text, and_, cast, func, literal_column, or_, select, text
from sqlalchemy.dialects.postgresql import ARRAY, array

from db.models import etiquetas_aplicadas, licitacion_tecnologia_score, licitaciones
from db.repositories.base import csv_values
from db.sql_fragments import (
    FOLD_DST_SQL,
    FOLD_SRC_SQL,
    FOLD_TABLE,
    ISO_MAX,
    ISO_MIN,
    columna_nucleo,
    escape_like,
    exclude_duplicados_presentacion_sql,
    fecha_valida_sql,
    fold_expr,
    importe_select_sql,
    importe_sql,
    lectura_tipada_activa,
    normaliza_codigo,
    tecnologia_tokens_sql,
    universo_producto_sql,
)
from shared.dto import FiltrosLicitacion
from shared.estados import abierta_core
from shared.procedimientos import codigo_tipo_contrato, textos_de_tipo_contrato

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# Cotas del guard ISO de las columnas de fecha. Vienen de
# ``db/sql_fragments.iso_guard``, que las documenta: rango lexicográfico y no
# regex, porque ``~`` no puede usar el btree de la columna y obliga a evaluar el
# patrón fila a fila. Este módulo necesita los extremos sueltos y no el texto ya
# compuesto, porque compila SA Core con ``compile_query`` en vez de interpolar
# SQL; eran dos constantes locales y ahora son las mismas de allí, así que
# ampliar el rango ya no puede cambiar sólo la mitad del repositorio.


def _iso_guard(column: Any) -> Any:
    """Cláusula SA Core que excluye fechas claramente malformadas."""
    return and_(column >= ISO_MIN, column < ISO_MAX)


# ── Núcleo tipado (T2): listado y cursor ──────────────────────────────────
# Las dos consultas calientes de este módulo filtran y ordenan por fecha e
# importe. Leen la columna que decide `db.sql_fragments.columna_nucleo` —la
# vieja con `NUCLEO_TIPADO_LECTURA` apagado, la sombra de `v133` encendido—, y
# todo se evalúa **en cada llamada**, no al importar: el flag se cambia por
# configuración y la vuelta atrás no puede exigir reiniciar el proceso.
#
# Con el flag apagado el SQL compilado es byte a byte el de antes; lo fija
# `tests/test_nucleo_tipado_consultas.py`.


def _nucleo(nombre: str) -> Any:
    """Columna SA Core de ``nombre`` para filtrar u ordenar: vieja o sombra."""
    return licitaciones.c[columna_nucleo(nombre)]


def _fecha_valida(nombre: str) -> Any:
    """Guarda de fecha bien formada en SA Core, gemela de ``fecha_valida_sql``.

    Apagado es :func:`_iso_guard` sobre el texto (parámetros ligados, como
    siempre). Encendido, el rango de ``timestamptz`` de ``fecha_valida_sql``
    sobre la sombra, que es un literal constante y no necesita parámetros.
    """
    if not lectura_tipada_activa():
        return _iso_guard(licitaciones.c[nombre])
    return text(fecha_valida_sql(nombre, "licitaciones"))


def _importe_proyectado() -> Any:
    """``importe`` para la lista de columnas del listado, con su nombre de siempre."""
    if not lectura_tipada_activa():
        return licitaciones.c.importe
    return literal_column(importe_sql("licitaciones")).label("importe")


def _dia_siguiente(iso_date: str) -> str | None:
    """``YYYY-MM-DD`` + 1 día, o ``None`` si esa fecha no existe en el calendario.

    ``fecha_limite`` no guarda un día, guarda el instante de cierre completo
    (``2026-08-28T14:00:00``: lo escribe ``to_iso_datetime`` desde
    ``scraper/codice_parser.py::_tender_deadline``). Por eso una cota superior
    dada por día no puede ser ``<= '2026-08-28'``: lexicográficamente eso deja
    fuera **todos** los expedientes que cierran ese mismo día a cualquier hora,
    que son justo los que la cota pretende incluir. La cota exacta es "menor que
    el día siguiente", y sigue siendo un rango sargable sobre
    ``idx_lic_fecha_limite``.

    El regex de la ruta acepta un ``2026-13-45`` bien formateado pero inexistente;
    aquí se descarta en silencio, igual que el resto de fechas malformadas del
    módulo, en vez de propagar un ``ValueError`` como 500.
    """
    try:
        return (date.fromisoformat(iso_date) + timedelta(days=1)).isoformat()
    except ValueError:
        return None


#: `objeto_tipo` con el que se etiqueta un expediente: el «favorito» de F1.6,
#: cuyo `objeto_id` es el `id_externo` de la licitación.
OBJETO_ETIQUETA_EXPEDIENTE: Final = "favorito"


def _etiqueta_requerida(
    etiqueta_id: int | None, organization_id: int | None
) -> tuple[int, int] | None:
    """``(organización, etiqueta)`` del filtro, o ``None`` si no se pidió.

    Una etiqueta sin organización **falla** en vez de filtrar por id a secas:
    los ids de `etiquetas` son globales, y un filtro que olvidara la
    organización casaría con lo etiquetado por otro cliente. La resuelve quien
    llama (la ruta, con la sesión delante), nunca este repositorio.
    """
    if etiqueta_id is None:
        return None
    if organization_id is None:
        raise ValueError("El filtro por etiqueta necesita la organización resuelta.")
    return int(organization_id), int(etiqueta_id)


def _plegado(column: Any) -> Any:
    """Versión SA Core de ``db.sql_fragments.fold_expr``: sin tildes y en minúsculas.

    El plegado tiene que aplicarse a los **dos** lados o no sirve de nada: el
    llamante pliega el término de búsqueda con ``FOLD_TABLE`` antes de mandarlo
    como parámetro. Se comparte la tabla de traducción con el fragmento de texto
    para que buscar "murcia" y "Murcía" no dependa de por qué superficie entre
    la consulta.

    Las dos tablas van como **literales** (``literal_column`` sobre
    ``FOLD_SRC_SQL``/``FOLD_DST_SQL``), no como ``func.translate(col, FOLD_SRC,
    FOLD_DST)``: con cadenas de Python, SQLAlchemy las convertía en dos
    parámetros ligados y la consulta llegaba como ``translate(col, $1, $2)``,
    que ningún índice de expresión reconoce en cuanto el plan es genérico (ver
    el comentario de ``FOLD_SRC_SQL``). Compilado, esto es carácter a carácter
    ``fold_expr("licitaciones.<columna>")``, la misma expresión que emiten los
    agregados; lo fija ``tests/test_s1_paridad_filtros.py``.
    """
    return func.lower(
        func.translate(column, literal_column(FOLD_SRC_SQL), literal_column(FOLD_DST_SQL))
    )


#: Dónde busca ``q``. Es la misma lista que arma
#: ``db/repositories/aggregates.py::build_licitaciones_where``, y tiene que
#: serlo: el listado y los KPIs de la misma pantalla salen de las dos, y hasta
#: 2026-09 buscaban en sitios distintos (aquí título + descripción, allí título
#: + órgano + id) sin plegar acentos en este lado. El mismo texto en la misma
#: caja daba dos recuentos. ``tests/test_s1_paridad_filtros.py`` los compara.
#: Universo de presentación del listado (ADR-026 D23): fuera las
#: republicaciones ``pending`` y ``confirmed``, como en el Radar. Es ``text()``
#: y no una subconsulta SA Core para que el SQL emitido sea la misma cadena que
#: en los agregados (``build_licitaciones_where``) y en la rama FTS.
_SIN_REPUBLICACIONES = text(exclude_duplicados_presentacion_sql("licitaciones.id_externo"))


#: Universo del listado (:func:`db.sql_fragments.universo_producto_sql`). Antes
#: era ``tecnologia`` informada, y dejaba fuera lo que entra por su CPV o solo
#: con la etiqueta del clasificador.
_UNIVERSO_PRODUCTO = text(universo_producto_sql("licitaciones"))


_COLUMNAS_BUSQUEDA = (
    licitaciones.c.titulo,
    licitaciones.c.descripcion,
    licitaciones.c.organo_contratacion,
    licitaciones.c.id_externo,
)


def _normaliza_codigo(code: str) -> str:
    """Código de lista controlada listo para comparar: sin ceros a la izquierda.

    La fuente publica ``01`` y ``1`` para el mismo procedimiento según el
    emisor. Es la misma normalización que hace ``shared/procedimientos.py`` al
    traducirlos a etiqueta; si el filtro no la aplicara, «Abierto» dejaría
    fuera a la mitad de los expedientes de algunos órganos y el desplegable
    parecería roto. Delega en ``db.sql_fragments.normaliza_codigo``: eran dos
    copias idénticas de la misma regla.
    """
    return normaliza_codigo(code)


def _codigo_en(column: Any, values: list[str]) -> Any:
    """``column`` coincide con alguno de ``values``, comparando normalizado.

    La normalización se aplica **a los dos lados**: al valor que llega del
    usuario en Python, y a la columna en SQL con el mismo ``ltrim``. Hacerlo
    sólo en Python dejaría fuera las filas guardadas como ``01``.
    """
    codigos = {_normaliza_codigo(v) for v in values if v and v.strip()}
    if not codigos:
        return text("1=1")
    # `NULLIF`+`COALESCE`: `ltrim('0','0')` deja '', que no es ningún código.
    normalizada = func.coalesce(func.nullif(func.ltrim(func.trim(column), "0"), ""), "0")
    return normalizada.in_(sorted(codigos))


def _tipos_de_contrato(values: list[str]) -> tuple[list[str], list[str]]:
    """``(códigos, textos plegados)`` que significan los tipos de ``values``.

    ``tipo_contrato`` guarda el código CODICE o el texto de cada fuente en su
    lengua, y el texto es la mayoría: «Serveis» 41.523 filas y «services» 2.149
    frente a 13.652 «2» (medido en producción el 2026-10-17). Filtrar solo por
    el código dejaba fuera tres de cada cuatro servicios
    (``shared.procedimientos.codigo_tipo_contrato``). Un valor que no se sabe
    traducir se busca como código, como antes.
    """
    codigos = sorted(
        {codigo_tipo_contrato(v) or _normaliza_codigo(v) for v in values if v and v.strip()}
    )
    textos = sorted({t for c in codigos for t in textos_de_tipo_contrato(c)})
    return codigos, textos


def _tipo_contrato_en(values: list[str]) -> Any:
    """:func:`_codigo_en` para ``tipo_contrato``: el código o el texto de la fuente."""
    codigos, textos = _tipos_de_contrato(values)
    por_codigo = _codigo_en(licitaciones.c.tipo_contrato, codigos)
    if not textos:
        return por_codigo
    return or_(por_codigo, literal_column(fold_expr("licitaciones.tipo_contrato")).in_(textos))


def _any_of(column: Any, values: list[str]) -> Any:
    """``col == v`` para un valor, ``col IN (…)`` para varios."""
    return column == values[0] if len(values) == 1 else column.in_(values)


def _tecnologia_en_csv(codes: list[str]) -> Any:
    """Casa ``codes`` contra el CSV de códigos que guarda cada fila.

    ``licitaciones.tecnologia`` no es un código, es ``"SAP,SALESFORCE"``: la
    igualdad dejaba fuera los expedientes multi-tecnología, así que filtrar por
    SAP escondía justo los que además llevan otra. Mismo universo que resuelve
    ``db/repositories/aggregates.py`` para los agregados de analytics —el
    listado y los KPIs de la misma pantalla tienen que contar lo mismo—.

    Hasta 2026-09 esto eran cuatro ``LIKE`` por código (igual, ``'c,%'``,
    ``'%,c,%'``, ``'%,c'``) sobre el CSV sin espacios. Ahora es el mismo ``&&``
    que emite ``db.sql_fragments.tecnologia_en_csv_sql`` para los agregados,
    con el lado de la columna tomado **literalmente** de
    ``tecnologia_tokens_sql``: esa expresión es la que indexaría el GIN
    propuesto, y una grafía propia de SQLAlchemy (``coalesce`` en minúscula,
    los literales como parámetros) no la reconocería. Misma semántica que los
    ``LIKE``: código entero del CSV, nunca subcadena, con los espacios fuera.

    El lado de los valores sí son parámetros, uno por código, y el ``CAST`` a
    ``TEXT[]`` hace lo que el ``::text[]`` del fragmento de texto.
    """
    tokens = literal_column(tecnologia_tokens_sql("licitaciones.tecnologia"), ARRAY(Text))
    return tokens.op("&&")(cast(array(codes), ARRAY(Text)))


# Columnas devueltas en listados (resumen)
_SUMMARY_COLS = [
    licitaciones.c.id_externo,
    licitaciones.c.titulo,
    licitaciones.c.organo_contratacion,
    licitaciones.c.importe,
    licitaciones.c.estado,
    licitaciones.c.fecha_publicacion,
    licitaciones.c.fecha_limite,
    licitaciones.c.ccaa,
    licitaciones.c.cpv,
    licitaciones.c.url,
    licitaciones.c.tecnologia,
    licitaciones.c.ml_tecnologias,
    licitaciones.c.ml_proba_max,
    licitaciones.c.ml_tech_principal,
    # F1.7: códigos crudos; la etiqueta la pone la consola con `/meta/filters`.
    licitaciones.c.procedimiento,
    licitaciones.c.tramitacion,
]


# Columnas de la bandeja «Próximas» del Radar (T5). Es ``_SUMMARY_COLS`` menos
# lo que un anuncio previo nunca trae (las tres columnas de ML: nadie ha
# clasificado un expediente que aún no tiene pliego) y **más
# ``fecha_inicio``**, que es la única razón por la que esta lista no puede salir
# del listado normal: ``_SUMMARY_COLS`` no la lleva, y sin ella la bandeja no
# puede decir para cuándo está prevista la compra.
_PROXIMAS_COLS = [
    licitaciones.c.id_externo,
    licitaciones.c.titulo,
    licitaciones.c.organo_contratacion,
    licitaciones.c.importe,
    licitaciones.c.estado,
    licitaciones.c.fecha_publicacion,
    licitaciones.c.fecha_inicio,
    licitaciones.c.ccaa,
    licitaciones.c.cpv,
    licitaciones.c.url,
    licitaciones.c.tecnologia,
]


_SORT_MAP: dict[str, Any] = {
    "fecha_publicacion": licitaciones.c.fecha_publicacion.desc(),
    "-fecha_publicacion": licitaciones.c.fecha_publicacion.asc(),
    "importe": licitaciones.c.importe.asc(),
    "-importe": licitaciones.c.importe.desc(),
    "titulo": licitaciones.c.titulo.asc(),
    "-titulo": licitaciones.c.titulo.desc(),
}


_DEFAULT_ORDER = licitaciones.c.fecha_publicacion.desc()


def _orden(sort: str | None) -> Any:
    """``ORDER BY`` del listado, resuelto contra el núcleo tipado vigente (T2).

    Mismo contrato que ``_SORT_MAP``/``_DEFAULT_ORDER`` —que se conservan para
    la búsqueda avanzada, fuera de las consultas calientes—, pero construido en
    cada llamada: con ``NUCLEO_TIPADO_LECTURA`` encendido ordena por la sombra,
    y un orden precompilado al importar se quedaría con la columna vieja.
    """
    fecha, importe = _nucleo("fecha_publicacion"), _nucleo("importe")
    ordenes: dict[str, Any] = {
        "fecha_publicacion": fecha.desc(),
        "-fecha_publicacion": fecha.asc(),
        "importe": importe.asc(),
        "-importe": importe.desc(),
        "titulo": licitaciones.c.titulo.asc(),
        "-titulo": licitaciones.c.titulo.desc(),
    }
    return ordenes.get(sort or "", fecha.desc())


#: Órdenes que admite el listado por cursor: los mismos seis que el de offset.
SORTS_CURSOR: Final = frozenset(_SORT_MAP)


def _orden_cursor(sort: str) -> tuple[Any, bool]:
    """``(columna, descendente)`` de un valor de ``sort``, con la semántica de ``_SORT_MAP``.

    Se resuelve en cada llamada, como :func:`_orden`: fecha e importe salen del
    núcleo tipado vigente (T2).
    """
    if sort not in SORTS_CURSOR:
        raise ValueError(f"orden de cursor desconocido: {sort!r}")
    nombre = sort.lstrip("-")
    columna = licitaciones.c.titulo if nombre == "titulo" else _nucleo(nombre)
    # `fecha_publicacion` es descendente sin signo; importe y título, ascendentes.
    descendente = (nombre == "fecha_publicacion") != sort.startswith("-")
    return columna, descendente


def _columnas_resumen() -> list[Any]:
    """``_SUMMARY_COLS`` con el importe que toca proyectar (T2)."""
    return [_importe_proyectado() if c is licitaciones.c.importe else c for c in _SUMMARY_COLS]


def _columnas_resumen_sql(alias: str) -> str:
    """Las mismas columnas que :func:`_columnas_resumen`, como texto (rama FTS)."""
    return ", ".join(
        importe_select_sql(alias) if c is licitaciones.c.importe else f"{alias}.{c.key}"
        for c in _SUMMARY_COLS
    )


class FiltrosMixin:
    """Traducción de los filtros del listado a cláusulas SA Core."""

    @staticmethod
    def _base_filters(
        filtros: FiltrosLicitacion | None = None,
        *,
        solo_universo: bool = True,
    ) -> list[Any]:
        """Devuelve lista de cláusulas SA Core para WHERE.

        Es el único sitio que traduce :class:`shared.dto.FiltrosLicitacion` a
        SQL Core; ``None`` equivale a «sin filtros».

        ``fecha_desde``/``fecha_hasta`` acotan **publicación** y
        ``cierre_desde``/``cierre_hasta`` acotan **cierre** (``fecha_limite``).
        Son ejes distintos y combinables: el listado que abre la tarjeta
        «Vencen 48h» de ``/resumen`` pide el segundo, que hasta ahora no
        existía y dejaba el enlace abriendo el catálogo entero.

        El ``WHERE`` nace con la exclusión de presentación de duplicados
        (ADR-026 D23, desde 2026-10-17): el listado esconde las republicaciones
        ``pending`` y ``confirmed`` igual que el Radar. Va aquí y no en cada
        llamador para que paginado, cursor y export —y los KPIs que comparten
        este ámbito vía ``build_licitaciones_where``— midan lo mismo. La ficha
        por id no pasa por aquí: un enlace guardado sigue respondiendo, y
        declara ``republicacion_de``.
        """
        filtros = filtros or FiltrosLicitacion()
        clauses: list[Any] = [_SIN_REPUBLICACIONES]

        if solo_universo:
            clauses.append(_UNIVERSO_PRODUCTO)

        if filtros.q and filtros.q.strip():
            like = f"%{escape_like(filtros.q.strip().translate(FOLD_TABLE).lower())}%"
            clauses.append(or_(*[_plegado(c).like(like) for c in _COLUMNAS_BUSQUEDA]))
        estados = csv_values(filtros.estado)
        if estados:
            clauses.append(_any_of(licitaciones.c.estado, estados))
        if filtros.solo_abiertas:
            # El juicio «sigue abierta» sale de `shared.estados`, en su forma
            # para SA Core: el `COALESCE` (y no un `NOT IN` a secas, que en SQL
            # descarta el NULL en silencio) está allí, escrito una vez, junto a
            # la forma de texto que usan los agregados.
            clauses.append(abierta_core(licitaciones.c.estado))
        ccaas = csv_values(filtros.ccaa)
        if ccaas:
            clauses.append(_any_of(licitaciones.c.ccaa, ccaas))
        tecnologias = csv_values(filtros.tecnologia)
        if tecnologias:
            clauses.append(_tecnologia_en_csv(tecnologias))

        if filtros.tecnologia_predicha:
            if filtros.min_proba_tech is not None:
                # Subquery EXISTS en licitacion_tecnologia_score
                sub = (
                    select(text("1"))
                    .select_from(licitacion_tecnologia_score)
                    .where(
                        and_(
                            licitacion_tecnologia_score.c.licitacion_id
                            == licitaciones.c.id_externo,
                            licitacion_tecnologia_score.c.tecnologia == filtros.tecnologia_predicha,
                            licitacion_tecnologia_score.c.probabilidad
                            >= float(filtros.min_proba_tech),
                        )
                    )
                )
                clauses.append(sub.exists())
            else:
                # El valor va escapado dentro del patrón: llega de la query y
                # un `%` lo convertía en comodín. La rama FTS escapa igual, de
                # modo que las dos casan el mismo conjunto.
                t = escape_like(filtros.tecnologia_predicha)
                clauses.append(
                    or_(
                        licitaciones.c.ml_tech_principal == filtros.tecnologia_predicha,
                        licitaciones.c.ml_tecnologias == filtros.tecnologia_predicha,
                        licitaciones.c.ml_tecnologias.like(f"{t},%"),
                        licitaciones.c.ml_tecnologias.like(f"%,{t},%"),
                        licitaciones.c.ml_tecnologias.like(f"%,{t}"),
                    )
                )

        # Fechas e importe van por `_nucleo`/`_fecha_valida` (T2): la columna la
        # decide `NUCLEO_TIPADO_LECTURA`. Apagado, es la de siempre.
        fecha_pub = _nucleo("fecha_publicacion")
        fecha_lim = _nucleo("fecha_limite")
        if filtros.fecha_desde and _DATE_RE.match(filtros.fecha_desde):
            clauses.append(fecha_pub >= filtros.fecha_desde)
        if filtros.fecha_hasta and _DATE_RE.match(filtros.fecha_hasta):
            clauses.append(fecha_pub <= filtros.fecha_hasta)

        # Ventana de cierre. El guard ISO va una sola vez aunque haya dos cotas
        # —son rangos sobre la misma columna y Postgres los funde en un único
        # recorrido del índice—, y hace falta aunque el ``>=`` ya ponga suelo:
        # el techo ``< '3000'`` no lo implica. Mismo par de predicados que
        # cuenta ``aggregates.overview_para_hoy`` para ``vencen_48h``, de modo
        # que la tarjeta y el listado que abre midan lo mismo.
        cierre_desde_ok = bool(filtros.cierre_desde and _DATE_RE.match(filtros.cierre_desde))
        hasta_exclusivo = (
            _dia_siguiente(filtros.cierre_hasta)
            if filtros.cierre_hasta and _DATE_RE.match(filtros.cierre_hasta)
            else None
        )
        if cierre_desde_ok or hasta_exclusivo:
            clauses.append(_fecha_valida("fecha_limite"))
        if cierre_desde_ok:
            clauses.append(fecha_lim >= filtros.cierre_desde)
        if hasta_exclusivo:
            clauses.append(fecha_lim < hasta_exclusivo)

        # ── F1.1: los ocho filtros que faltaban ──────────────────────────
        #
        # Todos son aditivos y ninguno cambia el resultado cuando no se pasa,
        # así que el listado de siempre sigue devolviendo lo mismo. Van aquí
        # —y no en cada llamante— porque `_base_filters` es lo que comparten
        # el listado, el cursor y el export: es la única forma de que el test
        # de paridad pueda exigir el mismo `COUNT(*)` en los tres.

        # Importe: NULL queda fuera en cuanto se pide cualquiera de las cotas.
        # Es lo correcto y hay que decirlo: «de 100k a 500k» no puede incluir
        # expedientes sin importe publicado, aunque alguno lo tuviera.
        if filtros.importe_min is not None:
            clauses.append(_nucleo("importe") >= float(filtros.importe_min))
        if filtros.importe_max is not None:
            clauses.append(_nucleo("importe") <= float(filtros.importe_max))

        # CPV **por prefijo**: es como se usa de verdad. `72` es «servicios de
        # TI» entero y `7222` una familia dentro. Igualdad exacta obligaría a
        # conocer los ocho dígitos, que nadie recuerda.
        cpvs = csv_values(filtros.cpv)
        if cpvs:
            clauses.append(or_(*[licitaciones.c.cpv.like(f"{escape_like(c)}%") for c in cpvs]))

        # Órgano: coincidencia por subcadena y plegada, igual que la búsqueda
        # libre. El autocompletado manda el nombre normalizado, pero un usuario
        # que escribe «ayuntamiento de madrid» a mano tiene que encontrarlo
        # igual — y hasta que exista el maestro de órganos (C1.2) el nombre es
        # todo lo que hay.
        organos = csv_values(filtros.organo)
        if organos:
            clauses.append(
                or_(
                    *[
                        _plegado(licitaciones.c.organo_contratacion).like(
                            f"%{escape_like(o.translate(FOLD_TABLE).lower())}%"
                        )
                        for o in organos
                    ]
                )
            )

        provincias = csv_values(filtros.provincia)
        if provincias:
            clauses.append(_any_of(licitaciones.c.provincia, provincias))

        # Códigos CODICE. Se comparan **normalizados** (sin ceros a la
        # izquierda) porque la fuente publica `01` y `1` para lo mismo según el
        # emisor: sin esto, filtrar por «Abierto» perdería la mitad de los
        # expedientes de algunos órganos. Es la misma normalización que aplica
        # `shared/procedimientos.py` al traducirlos.
        for columna, valores in (
            (licitaciones.c.procedimiento, csv_values(filtros.procedimiento)),
            (licitaciones.c.tramitacion, csv_values(filtros.tramitacion)),
        ):
            if valores:
                clauses.append(_codigo_en(columna, valores))
        if tipos := csv_values(filtros.tipo_contrato):
            clauses.append(_tipo_contrato_en(tipos))

        # Plazo restante en días, calculado en SQL sobre `fecha_limite` y sin
        # los estados terminales: un expediente adjudicado con fecha límite
        # futura no «vence en 5 días», ya no se puede licitar.
        if filtros.dias_restantes_max is not None:
            tope = (
                (datetime.now(UTC) + timedelta(days=int(filtros.dias_restantes_max)))
                .date()
                .isoformat()
            )
            clauses.append(_fecha_valida("fecha_limite"))
            # `<` y no `<=`: `_dia_siguiente` produce una cota **exclusiva**
            # (lo dice su docstring, y así la usan `cierre_hasta` y la rama
            # FTS). Con `<=` esta rama devolvía un día de más, así que el
            # mismo filtro daba un universo distinto según si el usuario había
            # escrito o no en la caja de búsqueda.
            clauses.append(fecha_lim < _dia_siguiente(tope))
            clauses.append(fecha_lim >= datetime.now(UTC).date().isoformat())
            clauses.append(abierta_core(licitaciones.c.estado))

        # Etiqueta de organización (F1.6) puesta al expediente como favorito.
        # Va en el `WHERE` y no filtrando la página en el cliente, que era lo que
        # hacía Detalle: así el total y las páginas son las del conjunto
        # etiquetado entero. La organización viaja con la etiqueta y entra en el
        # `EXISTS` —además del respaldo RLS de `v128`—: una etiqueta es dato de
        # un cliente, y sin ella en el predicado el filtro casaría con lo que
        # otra organización ha etiquetado con el mismo id.
        if etiqueta := _etiqueta_requerida(filtros.etiqueta_id, filtros.etiqueta_organization_id):
            org, eid = etiqueta
            ea = etiquetas_aplicadas
            clauses.append(
                select(literal_column("1"))
                .select_from(ea)
                .where(
                    and_(
                        ea.c.organization_id == org,
                        ea.c.etiqueta_id == eid,
                        ea.c.objeto_tipo == OBJETO_ETIQUETA_EXPEDIENTE,
                        ea.c.objeto_id == licitaciones.c.id_externo,
                    )
                )
                .exists()
            )

        return clauses
