"""Reglas de watchlist por criterio (keyword/CPV/importe/CCAA) — persistencia
server-side.

A diferencia de la watchlist de empresas (v36, ``services/watchlist.py``, cuyo eje
es la empresa), estas reglas vigilan **criterios de búsqueda**. Sustituyen el
``localStorage`` del frontend de mi-watchlist (RFC ux-mi-watchlist; ADR-014 §2: el
estado de usuario es server-side, ``localStorage`` solo caché/migración one-shot).

Este módulo cubre el **CRUD** y el *matching* sobre el dataset completo. El
*job de alertas por frecuencia* vive en ``scheduler/watchlist_rules_alerts.py``.

Desde S4.4 del plan 2026-09 v2 una regla no se agota en keyword + CPV +
importe + CCAA: también sabe de tecnología, órgano, procedimiento, tipo de
contrato, banda del Radar y plazo mínimo. Los seis criterios se aplican en el
MISMO ``_rule_clauses``, que es lo que hace que la vista previa y el detalle no
puedan divergir: los dos cuentan con ``count_matches``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select, text

from db.database import connect, connect_read
from db.models import compile_query, licitaciones
from db.repositories.base import rows_to_dicts
from db.repositories.watchlist_rules import bounded_match_counts, matches_pendientes
from db.sql_fragments import FOLD_TABLE, fold_expr, iso_guard
from services.dedupe import normalize_organo
from shared.estados import abierta_core

Frequency = Literal["immediate", "daily", "weekly"]

#: Bandas comerciales del Radar. El vocabulario lo fija
#: ``services/analytics/scoring._band``.
#:
#: **El orden de los argumentos de este ``Literal`` tiene que coincidir con el
#: de los otros tres sitios que declaran las mismas cuatro bandas**
#: (``api/routes/radar.py`` y dos DTO de ``shared/dto.py``), y no es una manía
#: de estilo: ``typing.Literal`` compara y hashea por CONJUNTO, así que
#: ``Literal["Descarte", …]`` y ``Literal["Caliente", …]`` son iguales para
#: Pydantic, que reutiliza el esquema del primero que construye. Cuál sea el
#: primero depende del orden en que se importan los routers, de modo que el
#: enumerado salía unas veces en un orden y otras en el contrario: el job
#: «Codegen Drift Check» fallaba de forma intermitente sobre una línea de
#: ``web/src/generated/api.d.ts`` que nadie había tocado. Un gate que falla por
#: azar deja de leerse.
Banda = Literal["Caliente", "Atractiva", "Tibia", "Descarte"]

#: La escala ordinal, de menor a mayor, que es lo que ``banda_min`` necesita
#: para comparar. Vive aquí y no en el orden del ``Literal`` de arriba
#: precisamente porque aquel no puede llevar significado: es un conjunto.
ORDEN_BANDAS: tuple[Banda, ...] = ("Descarte", "Tibia", "Atractiva", "Caliente")

#: Techo de filas que se puntúan para resolver ``banda_min``. Es el mismo que
#: el conteo acotado del listado: por encima, lo que el usuario necesita es
#: afinar la regla, no un dígito más.
MAX_CANDIDATAS_BANDA = 1000


class WatchlistRule(BaseModel):
    """Regla de seguimiento por criterio. ``id`` es ``None`` hasta persistir."""

    id: int | None = None
    nombre: str | None = None
    keyword: str | None = None
    cpv: str | None = None
    min_importe: float | None = None
    ccaa: str | None = None
    frequency: Frequency = "daily"
    active: bool = True
    organization_id: int | None = None
    visibility: Literal["private", "organization"] = "private"
    # ── Criterios de S4.4. Todos ``None`` por defecto, que significa «este
    # criterio no filtra»: por eso las reglas que ya existían no cambian de
    # resultado al desplegar esta revisión.
    tecnologia: str | None = None
    organo: str | None = None
    procedimiento: str | None = None
    tipo_contrato: str | None = None
    banda_min: Banda | None = None
    plazo_min_dias: int | None = None

    @property
    def organo_norm(self) -> str | None:
        """El órgano plegado con ``services/dedupe.normalize_organo``.

        Se calcula aquí y se **persiste** en ``watchlist_rules.organo_norm``:
        normalizar en cada consulta obligaría a aplicar la función sobre la
        columna de la tabla grande, y una expresión sobre la columna no puede
        usar índice.
        """
        return normalize_organo(self.organo)


def create_rule(
    user_key: str,
    rule: WatchlistRule,
    *,
    user_id: int | None = None,
    organization_id: int | None = None,
    visibility: str = "private",
) -> int:
    """Persiste una regla nueva y devuelve su id."""
    with connect() as c:
        row = c.execute(
            "INSERT INTO watchlist_rules "
            "(user_key, user_id, nombre, keyword, cpv, min_importe, ccaa, "
            " frequency, active, organization_id, visibility, "
            " tecnologia, organo, organo_norm, procedimiento, tipo_contrato, "
            " banda_min, plazo_min_dias) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "        %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                user_key,
                user_id,
                rule.nombre,
                rule.keyword,
                rule.cpv,
                rule.min_importe,
                rule.ccaa,
                rule.frequency,
                1 if rule.active else 0,
                organization_id,
                visibility,
                rule.tecnologia,
                rule.organo,
                rule.organo_norm,
                rule.procedimiento,
                rule.tipo_contrato,
                rule.banda_min,
                rule.plazo_min_dias,
            ),
        ).fetchone()
    return int(row[0]) if row else 0


#: Proyección de una regla. Una sola constante para las dos ramas del listado:
#: cuando eran dos literales, añadir un criterio obligaba a acordarse de los
#: dos, y el que se olvidara devolvía la regla sin ese filtro — es decir, una
#: regla más ancha de la que el usuario escribió.
_COLS_REGLA = (
    "id, nombre, keyword, cpv, min_importe, ccaa, frequency, active, "
    "organization_id, visibility, tecnologia, organo, procedimiento, "
    "tipo_contrato, banda_min, plazo_min_dias"
)


def _fila_a_regla(row: Sequence[Any]) -> WatchlistRule:
    return WatchlistRule(
        id=row[0],
        nombre=row[1],
        keyword=row[2],
        cpv=row[3],
        min_importe=row[4],
        ccaa=row[5],
        frequency=row[6],
        active=bool(row[7]),
        organization_id=row[8],
        visibility=row[9],
        tecnologia=row[10],
        organo=row[11],
        procedimiento=row[12],
        tipo_contrato=row[13],
        banda_min=row[14],
        plazo_min_dias=row[15],
    )


def list_rules(user_key: str, organization_id: int | None = None) -> list[WatchlistRule]:
    """Reglas de un usuario, más recientes primero."""
    with connect() as c:
        if organization_id is None:
            rows = c.execute(
                f"SELECT {_COLS_REGLA} FROM watchlist_rules WHERE user_key = %s "  # noqa: S608
                "ORDER BY created_at DESC, id DESC",
                (user_key,),
            ).fetchall()
        else:
            rows = c.execute(
                f"SELECT {_COLS_REGLA} FROM watchlist_rules "  # noqa: S608
                "WHERE organization_id = %s "
                "AND (visibility = 'organization' OR user_key = %s) "
                "ORDER BY created_at DESC, id DESC",
                (organization_id, user_key),
            ).fetchall()
    return [_fila_a_regla(row) for row in rows]


def update_rule(
    user_key: str,
    rule_id: int,
    rule: WatchlistRule,
    organization_id: int | None = None,
) -> bool:
    """Actualiza una regla propia. ``False`` si no existe o no es del usuario."""
    values = (
        rule.nombre,
        rule.keyword,
        rule.cpv,
        rule.min_importe,
        rule.ccaa,
        rule.frequency,
        1 if rule.active else 0,
        rule.tecnologia,
        rule.organo,
        rule.organo_norm,
        rule.procedimiento,
        rule.tipo_contrato,
        rule.banda_min,
        rule.plazo_min_dias,
    )
    sets = (
        "nombre = %s, keyword = %s, cpv = %s, min_importe = %s, ccaa = %s, "
        "frequency = %s, active = %s, tecnologia = %s, organo = %s, "
        "organo_norm = %s, procedimiento = %s, tipo_contrato = %s, "
        "banda_min = %s, plazo_min_dias = %s"
    )
    with connect() as c:
        if organization_id is None:
            cur = c.execute(
                f"UPDATE watchlist_rules SET {sets} "  # noqa: S608
                "WHERE id = %s AND user_key = %s",
                (*values, rule_id, user_key),
            )
        else:
            cur = c.execute(
                f"UPDATE watchlist_rules SET {sets} "  # noqa: S608
                "WHERE id = %s AND user_key = %s AND organization_id = %s",
                (*values, rule_id, user_key, organization_id),
            )
        return bool(cur.rowcount > 0)


def set_active(user_key: str, rule_id: int, active: bool) -> bool:
    """Activa o pausa una regla propia."""
    with connect() as c:
        cur = c.execute(
            "UPDATE watchlist_rules SET active = %s WHERE id = %s AND user_key = %s",
            (1 if active else 0, rule_id, user_key),
        )
        return bool(cur.rowcount > 0)


def delete_rule(user_key: str, rule_id: int, organization_id: int | None = None) -> bool:
    """Borra una regla propia. ``False`` si no existe o no es del usuario."""
    with connect() as c:
        if organization_id is None:
            cur = c.execute(
                "DELETE FROM watchlist_rules WHERE id = %s AND user_key = %s",
                (rule_id, user_key),
            )
        else:
            cur = c.execute(
                "DELETE FROM watchlist_rules WHERE id = %s AND user_key = %s AND organization_id = %s",
                (rule_id, user_key, organization_id),
            )
        return bool(cur.rowcount > 0)


def delete_all_for_user(user_key: str) -> int:
    """Borra todas las reglas del usuario (GDPR). Devuelve el numero de filas borradas."""
    with connect() as c:
        cur = c.execute("DELETE FROM watchlist_rules WHERE user_key = %s", (user_key,))
        return int(cur.rowcount)


def deactivate_all_for_user(user_key: str) -> int:
    """Pausa todas las reglas del usuario. Devuelve cuántas estaban activas.

    Es la «baja» del enlace que va al pie de cada digest: no borra nada —las
    reglas siguen en Mi Watchlist y se reactivan desde allí— pero corta el
    correo de inmediato, que es lo único que quien pulsa ese enlace quiere.
    """
    with connect() as c:
        cur = c.execute(
            "UPDATE watchlist_rules SET active = 0 WHERE user_key = %s AND active = 1",
            (user_key,),
        )
        return int(cur.rowcount)


# ---------------------------------------------------------------------------
# Matching sobre el dataset completo
#
# RFC ux-mi-watchlist: el matching aplica keyword + CPV + min_importe + ccaa
# (no solo keyword/ccaa como el frontend), y el conteo se calcula en backend
# sobre TODO el dataset (no un ``limit=20`` cliente). SQLAlchemy Core →
# parametrizado (sin SQL string-built, sin S608).
# ---------------------------------------------------------------------------

_MATCH_COLS = (
    licitaciones.c.id_externo,
    licitaciones.c.titulo,
    licitaciones.c.organo_contratacion,
    licitaciones.c.importe,
    licitaciones.c.cpv,
    licitaciones.c.ccaa,
    licitaciones.c.estado,
    licitaciones.c.fecha_publicacion,
    licitaciones.c.url,
)


def _escape_like(s: str) -> str:
    """Escapa wildcards LIKE (%, _) del input de usuario."""
    return s.replace("%", r"\%").replace("_", r"\_")


def _hoy(hoy_iso: str | None) -> date:
    """Fecha de corte del predicado temporal.

    Se inyecta y no se lee del reloj dentro del predicado —mismo criterio que
    ``scoring_candidates``— para que la vista previa y el detalle de una regla
    usen EXACTAMENTE el mismo día aunque la pasada cruce la medianoche.
    """
    if hoy_iso:
        return date.fromisoformat(hoy_iso[:10])
    return datetime.now(UTC).date()


def _clausula_tecnologia(tecnologia: str) -> Any:
    """«Esta tecnología está en el CSV de la fila», no ``tecnologia = %s``.

    ``licitaciones.tecnologia`` guarda ``"SAP,SALESFORCE"``: la igualdad se
    dejaba fuera todos los expedientes multi-tecnología, que es el defecto que
    ``db.sql_fragments.tecnologia_en_csv_sql`` ya corrigió en el listado y los
    agregados. Aquí se escribe con ``text()`` porque el resto de la regla se
    compone con SA Core y el fragmento compartido emite texto; el valor viaja
    como bind param, nunca interpolado.
    """
    return text(
        "EXISTS (SELECT 1 FROM unnest(string_to_array("
        "COALESCE(licitaciones.tecnologia, ''), ',')) AS _tec(code) "
        "WHERE trim(_tec.code) = :wr_tecnologia)"
    ).bindparams(wr_tecnologia=tecnologia)


def _clausula_organo(organo_norm: str) -> Any:
    """Órgano por coincidencia sobre la forma plegada de los dos lados.

    El needle ya viene normalizado con ``services/dedupe.normalize_organo``
    (sin acentos, sin formas societarias, en minúsculas) y la columna se pliega
    con ``db.sql_fragments.fold_expr``, que es la misma aproximación que usan
    el ranking de órganos y el constructor de filtros del Resumen. Sin plegar
    los dos lados, «Ayuntamiento de Alcañiz» y «ayuntamiento de alcaniz» eran
    dos órganos distintos y la regla no disparaba nunca.
    """
    patron = f"%{_escape_like(organo_norm).translate(FOLD_TABLE)}%"
    return text(f"{fold_expr('licitaciones.organo_contratacion')} LIKE :wr_organo").bindparams(
        wr_organo=patron
    )


def _clausulas_universo_puntuable(hoy_iso: str | None) -> list[Any]:
    """El universo del Radar: estado no terminal **y** plazo vivo.

    Es literalmente el predicado de ``AggregateRepository.scoring_candidates``
    —``abierta_core`` sobre ``estado`` más la guarda ISO y el corte de hoy sobre
    ``fecha_limite``— y no una reescritura parecida: una banda solo significa
    algo dentro del conjunto sobre el que el Radar la calcula. Puntuar un
    expediente cerrado, o uno cuyo plazo venció, daría una banda que en el Radar
    no existe.
    """
    return [
        abierta_core(licitaciones.c.estado),
        text(iso_guard("licitaciones.fecha_limite")),
        licitaciones.c.fecha_limite >= _hoy(hoy_iso).isoformat(),
    ]


def _rule_clauses(rule: WatchlistRule, *, hoy_iso: str | None = None) -> list[Any]:
    """Traduce los filtros de la regla a condiciones SQLAlchemy.

    Aplica TODOS los criterios: keyword (título/descripción), cpv (prefijo),
    min_importe (>=), ccaa (=), tecnología (explode del CSV), órgano (plegado),
    procedimiento, tipo de contrato, plazo mínimo y —vía el universo puntuable—
    banda mínima del Radar. El CPV deja de ser un control muerto.

    ``banda_min`` aporta **aquí** el universo puntuable y nada más: el score del
    Radar se calcula en proceso (``services/analytics/scoring``) a partir de
    señales que no viven en una columna, así que la banda concreta la filtra
    :func:`_ids_desde_banda` sobre el resultado de este predicado. Las dos
    mitades las aplican por igual la vista previa y el detalle, que es lo que
    garantiza la paridad de sus totales.

    La keyword usa ``ILIKE``, no ``LIKE``: en Postgres ``LIKE`` distingue caja,
    así que una regla escrita "sap" o "erp" no casaba con un corpus donde el
    acrónimo va en mayúsculas, y el fallo era mudo — badge a 0, pestaña vacía y,
    sobre todo, ``matches_since`` (que comparte este predicado) nunca devolvía
    nada, con lo que el job de alertas jamás disparaba. El resto del producto ya
    buscaba con ``ILIKE`` (``db/repositories/aggregates.py``), así que esto
    además alinea la regla con lo que el usuario ve en el buscador. El CPV se
    queda con ``LIKE``: es un prefijo numérico y la caja no juega.
    """
    clauses: list[Any] = []
    if rule.keyword:
        like = f"%{_escape_like(rule.keyword)}%"
        clauses.append(
            or_(
                licitaciones.c.titulo.ilike(like),
                licitaciones.c.descripcion.ilike(like),
            )
        )
    if rule.cpv:
        clauses.append(licitaciones.c.cpv.like(f"{_escape_like(rule.cpv)}%"))
    if rule.min_importe is not None:
        clauses.append(licitaciones.c.importe >= rule.min_importe)
    if rule.ccaa:
        clauses.append(licitaciones.c.ccaa == rule.ccaa)
    if rule.tecnologia:
        clauses.append(_clausula_tecnologia(rule.tecnologia))
    organo_norm = rule.organo_norm
    if organo_norm:
        clauses.append(_clausula_organo(organo_norm))
    if rule.procedimiento:
        clauses.append(licitaciones.c.procedimiento == rule.procedimiento)
    if rule.tipo_contrato:
        clauses.append(licitaciones.c.tipo_contrato == rule.tipo_contrato)
    if rule.plazo_min_dias is not None:
        corte = (_hoy(hoy_iso) + timedelta(days=int(rule.plazo_min_dias))).isoformat()
        clauses.append(text(iso_guard("licitaciones.fecha_limite")))
        clauses.append(licitaciones.c.fecha_limite >= corte)
    if rule.banda_min:
        clauses.extend(_clausulas_universo_puntuable(hoy_iso))
    return clauses


def _ids_desde_banda(rule: WatchlistRule, *, hoy_iso: str | None = None) -> list[str]:
    """``id_externo`` de la regla cuya banda del Radar llega a ``banda_min``.

    Dos pasos y los dos necesarios:

    1. **SQL** acota al universo puntuable con el resto de criterios de la
       regla (``_rule_clauses`` ya mete ``_clausulas_universo_puntuable``). Son
       del orden de mil filas, no 1,6 millones.
    2. **El scorer del Radar** puntúa exactamente esas filas en modo
       *page-aligned* (``ScoringFilters.ids``) y se queda con las que alcanzan
       la banda. No hay una columna con el score —depende del perfil, de los
       percentiles del universo vivo y de la señal técnica— así que empujarlo
       a SQL exigiría una reimplementación paralela que divergiría del Radar al
       primer cambio de pesos, y la banda dejaría de significar lo mismo en las
       dos pantallas.

    El techo de :data:`MAX_CANDIDATAS_BANDA` es el mismo del conteo acotado del
    listado: por encima, lo que hace falta es afinar la regla.
    """
    from services.analytics.scoring import ScoringFilters, get_scoring

    clauses = _rule_clauses(rule, hoy_iso=hoy_iso)
    stmt = select(licitaciones.c.id_externo).select_from(licitaciones)
    if clauses:
        stmt = stmt.where(and_(*clauses))
    sql, params = compile_query(stmt.limit(MAX_CANDIDATAS_BANDA))
    with connect_read() as c:
        candidatas = [str(row[0]) for row in c.execute(sql, params).fetchall()]
    if not candidatas:
        return []

    minimo = ORDEN_BANDAS.index(rule.banda_min) if rule.banda_min else 0
    resultado = get_scoring(ScoringFilters(ids=candidatas, limit=len(candidatas)))
    return [
        oportunidad.id_externo
        for oportunidad in resultado.opportunities
        if oportunidad.band in ORDEN_BANDAS and ORDEN_BANDAS.index(oportunidad.band) >= minimo
    ]


def count_matches(rule: WatchlistRule, *, hoy_iso: str | None = None) -> int:
    """Conteo de matches sobre el dataset COMPLETO (no un ``limit=20`` cliente).

    Es la ÚNICA fuente del total: la vista previa (``POST /preview``) y el
    detalle (``GET /{id}/matches``) llaman aquí los dos, así que su ``total`` no
    puede divergir por construcción — que es el criterio de paridad de S4.4.
    """
    if rule.banda_min:
        return len(_ids_desde_banda(rule, hoy_iso=hoy_iso))
    clauses = _rule_clauses(rule, hoy_iso=hoy_iso)
    stmt = select(func.count()).select_from(licitaciones)
    if clauses:
        stmt = stmt.where(and_(*clauses))
    sql, params = compile_query(stmt)
    with connect_read() as c:
        row = c.execute(sql, params).fetchone()
    return int(row[0]) if row else 0


def count_matches_bounded(rules: Sequence[WatchlistRule]) -> list[int]:
    """Conteo ACOTADO de varias reglas de una sentada (badge del listado).

    ``count_matches`` es exacto y por eso caro: escaneo secuencial completo por
    regla. Para el listado —donde el número solo alimenta un badge— se usa el
    conteo con techo de ``db.repositories.watchlist_rules``, que además resuelve
    todas las reglas con una única conexión en vez de una por regla. Un valor
    igual a ``MATCH_COUNT_CAP`` quiere decir «al menos tantas».
    """
    return bounded_match_counts([_rule_clauses(rule) for rule in rules])


def list_matches(
    rule: WatchlistRule, *, limit: int = 50, hoy_iso: str | None = None
) -> list[dict[str, Any]]:
    """Matches de la regla (preview en vivo), más recientes primero."""
    clauses = _rule_clauses(rule, hoy_iso=hoy_iso)
    if rule.banda_min:
        # El filtro de banda no cabe en el WHERE (ver `_ids_desde_banda`), así
        # que se resuelve antes y entra como una pertenencia por id. Sigue
        # siendo el mismo predicado que cuenta `count_matches`.
        ids = _ids_desde_banda(rule, hoy_iso=hoy_iso)
        if not ids:
            return []
        clauses = [licitaciones.c.id_externo.in_(ids)]
    stmt = select(*_MATCH_COLS).select_from(licitaciones)
    if clauses:
        stmt = stmt.where(and_(*clauses))
    stmt = stmt.order_by(licitaciones.c.fecha_publicacion.desc()).limit(limit)
    sql, params = compile_query(stmt)
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, params))


def matches_since(
    rule: WatchlistRule,
    since: str | None,
    *,
    limit: int = 50,
    user_key: str | None = None,
) -> list[dict[str, Any]]:
    """Matches de la regla desde ``since`` que aún no se han notificado.

    ``since`` es una fecha ISO ``YYYY-MM-DD`` y el corte es **inclusivo**. Fue
    exclusivo (``>``) hasta el 2026-08-30 y esa desigualdad, combinada con una
    ventana que el job adelanta en cada evaluación, hacía que ninguna licitación
    publicada el día en que la regla se evaluaba pudiera notificarse jamás: el
    job quedaba mudo sin error, sin log y con sus tests en verde, porque todos
    sembraban días distintos. El razonamiento completo está en
    ``db.repositories.watchlist_rules``.

    ``user_key`` activa el anti-join contra las notificaciones ya escritas, que
    es lo que hace seguro el solape de ventanas. Sin él —vista previa, tests que
    no ejercen el job— la función es un listado con corte temporal y basta.
    """
    clauses = _rule_clauses(rule)
    if rule.banda_min:
        ids = _ids_desde_banda(rule)
        if not ids:
            return []
        clauses = [licitaciones.c.id_externo.in_(ids)]
    return matches_pendientes(
        clauses,
        _MATCH_COLS,
        desde=since,
        limit=limit,
        user_key=user_key,
    )
