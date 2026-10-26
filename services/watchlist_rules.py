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

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import ColumnElement, and_, bindparam, func, literal_column, or_, text

from db.models import licitaciones
from db.repositories.watchlist_rules import (
    ValoresRegla,
    actualizar_regla,
    borrar_regla,
    borrar_reglas_de_usuario,
    bounded_match_counts,
    contar_matches,
    daily_match_counts,
    filas_de_reglas,
    filas_de_reglas_activas,
    ids_que_casan,
    insertar_regla,
    listar_matches,
    matches_pendientes,
    pausar_reglas_de_usuario,
)
from db.sql_fragments import FOLD_TABLE, escape_like, fold_expr, iso_guard, palabras_de_organo
from observability.logging import get_logger
from services.dedupe import normalize_organo
from shared.dto import RadarBanda
from shared.estados import abierta_core
from shared.procedimientos import codigo_tipo_contrato, textos_de_tipo_contrato

log = get_logger(__name__)

Frequency = Literal["immediate", "daily", "weekly"]

#: Las bandas son ``RadarBanda`` de ``shared/dto/``, la declaración canónica.
#: Aquí vivía una copia (``Banda``) alineada a mano; como ``typing.Literal``
#: compara por conjunto, dos copias en distinto orden hacían que el enumerado
#: del contrato saliera en el orden de quien se importase antes, y el «Codegen
#: Drift Check» fallaba al azar. Una sola declaración lo cierra.
#:
#: La escala ordinal, de menor a mayor, que es lo que ``banda_min`` necesita
#: para comparar. Vive aquí y no en el orden del ``Literal`` precisamente
#: porque aquel no puede llevar significado: es un conjunto.
ORDEN_BANDAS: tuple[RadarBanda, ...] = ("Descarte", "Tibia", "Atractiva", "Caliente")

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
    banda_min: RadarBanda | None = None
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


def _valores(rule: WatchlistRule) -> ValoresRegla:
    """Las columnas editables de ``rule`` tal y como las guarda la tabla."""
    return ValoresRegla(
        nombre=rule.nombre,
        keyword=rule.keyword,
        cpv=rule.cpv,
        min_importe=rule.min_importe,
        ccaa=rule.ccaa,
        frequency=rule.frequency,
        active=1 if rule.active else 0,
        tecnologia=rule.tecnologia,
        organo=rule.organo,
        organo_norm=rule.organo_norm,
        procedimiento=rule.procedimiento,
        tipo_contrato=rule.tipo_contrato,
        banda_min=rule.banda_min,
        plazo_min_dias=rule.plazo_min_dias,
    )


def create_rule(
    user_key: str,
    rule: WatchlistRule,
    *,
    user_id: int | None = None,
    organization_id: int | None = None,
    visibility: str = "private",
) -> int:
    """Persiste una regla nueva y devuelve su id."""
    return insertar_regla(
        user_key,
        _valores(rule),
        user_id=user_id,
        organization_id=organization_id,
        visibility=visibility,
    )


def _fila_a_regla(row: Mapping[str, Any]) -> WatchlistRule:
    return WatchlistRule(
        id=row["id"],
        nombre=row["nombre"],
        keyword=row["keyword"],
        cpv=row["cpv"],
        min_importe=row["min_importe"],
        ccaa=row["ccaa"],
        frequency=row["frequency"],
        active=bool(row["active"]),
        organization_id=row["organization_id"],
        visibility=row["visibility"],
        tecnologia=row["tecnologia"],
        organo=row["organo"],
        procedimiento=row["procedimiento"],
        tipo_contrato=row["tipo_contrato"],
        banda_min=row["banda_min"],
        plazo_min_dias=row["plazo_min_dias"],
    )


def list_rules(
    user_key: str, organization_id: int | None = None, *, user_id: int | None = None
) -> list[WatchlistRule]:
    """Reglas de un usuario, más recientes primero."""
    filas = filas_de_reglas(user_key, organization_id, user_id=user_id)
    return [_fila_a_regla(fila) for fila in filas]


def update_rule(
    user_key: str,
    rule_id: int,
    rule: WatchlistRule,
    organization_id: int | None = None,
    *,
    user_id: int | None = None,
) -> bool:
    """Actualiza una regla propia. ``False`` si no existe o no es del usuario."""
    return actualizar_regla(user_key, rule_id, _valores(rule), organization_id, user_id=user_id)


def delete_rule(
    user_key: str,
    rule_id: int,
    organization_id: int | None = None,
    *,
    user_id: int | None = None,
) -> bool:
    """Borra una regla propia. ``False`` si no existe o no es del usuario."""
    return borrar_regla(user_key, rule_id, organization_id, user_id=user_id)


def delete_all_for_user(user_key: str, *, user_id: int | None = None) -> int:
    """Borra todas las reglas del usuario (GDPR). Devuelve el numero de filas borradas."""
    return borrar_reglas_de_usuario(user_key, user_id=user_id)


def deactivate_all_for_user(user_key: str, *, user_id: int | None = None) -> int:
    """Pausa todas las reglas del usuario. Devuelve cuántas estaban activas.

    Es la «baja» del enlace que va al pie de cada digest: no borra nada —las
    reglas siguen en Mi Watchlist y se reactivan desde allí— pero corta el
    correo de inmediato, que es lo único que quien pulsa ese enlace quiere.
    """
    return pausar_reglas_de_usuario(user_key, user_id=user_id)


# ---------------------------------------------------------------------------
# Matching sobre el dataset completo
#
# RFC ux-mi-watchlist: el matching aplica keyword + CPV + min_importe + ccaa
# (no solo keyword/ccaa como el frontend), y el conteo se calcula en backend
# sobre TODO el dataset (no un ``limit=20`` cliente). SQLAlchemy Core →
# parametrizado (sin SQL string-built, sin S608). Aquí se construyen las
# cláusulas; las sentencias se ejecutan en ``db/repositories/watchlist_rules.py``
# (ADR-022).
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
    """Órgano por las palabras de su nombre, plegadas en los dos lados.

    Casa si el órgano contiene **cada** palabra que distingue al de la regla
    (:func:`db.sql_fragments.palabras_de_organo`): «Diputación de Granada»
    avisa de lo de la «Diputación Provincial de Granada», y «Ayuntamiento de
    Barcelona» de lo del «Ajuntament de Barcelona». Es el mismo criterio que el
    órgano de la frase del Investigador, desde donde se crean reglas con un
    clic: la regla avisa de lo que la búsqueda enseñaba.

    El needle ya viene normalizado con ``services/dedupe.normalize_organo``
    (sin acentos, sin formas societarias, en minúsculas) y la columna se pliega
    con ``db.sql_fragments.fold_expr``, que es la misma aproximación que usan
    el ranking de órganos y el constructor de filtros del Resumen. Sin plegar
    los dos lados, «Ayuntamiento de Alcañiz» y «ayuntamiento de alcaniz» eran
    dos órganos distintos y la regla no disparaba nunca.

    El plegado entra como ``literal_column`` y la comparación es el ``.like()``
    de SA Core, no un ``text()`` montado con f-string: el fragmento es una
    constante de ``db/sql_fragments`` y el needle ya viajaba como bind param,
    pero Semgrep (``avoid-sqlalchemy-text``) no distingue una cosa de la otra y
    su hallazgo dejaba en rojo el barrido semanal de ``security.yml``.

    El ``bindparam`` lleva nombre propio a propósito: sin él, SA deriva el del
    parámetro anónimo del texto de la columna —tildes y comillas incluidas— y
    ``compile_query`` no lo encuentra al ordenar los posicionales.
    """
    plegado: ColumnElement[str] = literal_column(fold_expr("licitaciones.organo_contratacion"))
    palabras = palabras_de_organo(organo_norm) or [(organo_norm.translate(FOLD_TABLE),)]
    return and_(
        *(
            or_(
                *(
                    plegado.like(bindparam("wr_organo", f"%{escape_like(v)}%", unique=True))
                    for v in variantes
                )
            )
            for variantes in palabras
        )
    )


def _clausula_procedimiento(procedimiento: str) -> Any:
    """El código CODICE de la regla contra la columna, sin ceros a la izquierda.

    La fuente publica ``01`` y ``1`` para el mismo procedimiento; el filtro del
    listado y el del Investigador ya comparan así
    (``db.repositories.base.ambito_busqueda_sql``), y una regla creada desde
    una búsqueda tiene que casar con las mismas filas.
    """
    limpio = procedimiento.strip()
    codigo = str(int(limpio)) if limpio.isdigit() else limpio
    return _sin_ceros(licitaciones.c.procedimiento) == bindparam(
        "wr_procedimiento", codigo, unique=True
    )


def _sin_ceros(columna: Any) -> Any:
    """``columna`` sin ceros a la izquierda (``01`` → ``1``), como la normaliza
    ``shared.procedimientos``; ``ltrim`` deja ``''`` de un ``0`` y eso no es
    ningún código."""
    return func.coalesce(func.nullif(func.ltrim(func.trim(columna), "0"), ""), "0")


def _clausula_tipo_contrato(tipo_contrato: str) -> Any:
    """El tipo de contrato de la regla, escrito como código o como texto.

    La columna mezcla el código CODICE («2») con el texto de cada fuente en su
    lengua («Serveis», «services»), y el texto es la mayoría
    (``shared.procedimientos.codigo_tipo_contrato``). Por igualdad, una regla
    «servicios» no casaba con ninguna fila. Un valor que no se sabe traducir se
    compara tal cual, como antes.
    """
    codigo = codigo_tipo_contrato(tipo_contrato)
    if codigo is None:
        return licitaciones.c.tipo_contrato == tipo_contrato
    plegado: ColumnElement[str] = literal_column(fold_expr("licitaciones.tipo_contrato"))
    por_codigo = _sin_ceros(licitaciones.c.tipo_contrato) == bindparam(
        "wr_tipo_contrato", codigo, unique=True
    )
    if not (textos := textos_de_tipo_contrato(codigo)):
        return por_codigo
    return or_(
        por_codigo,
        *(plegado == bindparam("wr_tipo_contrato_texto", t, unique=True) for t in textos),
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
        like = f"%{escape_like(rule.keyword)}%"
        clauses.append(
            or_(
                licitaciones.c.titulo.ilike(like),
                licitaciones.c.descripcion.ilike(like),
            )
        )
    if rule.cpv:
        clauses.append(licitaciones.c.cpv.like(f"{escape_like(rule.cpv)}%"))
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
        clauses.append(_clausula_procedimiento(rule.procedimiento))
    if rule.tipo_contrato:
        clauses.append(_clausula_tipo_contrato(rule.tipo_contrato))
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

    candidatas = ids_que_casan(_rule_clauses(rule, hoy_iso=hoy_iso), limit=MAX_CANDIDATAS_BANDA)
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
    return contar_matches(_rule_clauses(rule, hoy_iso=hoy_iso))


#: Semanas de historia que mira la vista previa de ruido (F5.5).
SEMANAS_PREVIEW = 8

#: Coincidencias por semana por encima de las cuales la vista previa avisa.
#:
#: Cincuenta es aproximadamente «diez al día laborable»: por ahí es donde una
#: alerta deja de leerse y empieza a archivarse en bloque, que es peor que no
#: tenerla —el usuario deja de mirar también las buenas—. Es configurable
#: porque el umbral correcto depende del tamaño del equipo, y se **declara**
#: en la respuesta para que la UI no tenga que repetirlo.
UMBRAL_RUIDO_SEMANAL = 50


def serie_semanal(rule: WatchlistRule, *, semanas: int = SEMANAS_PREVIEW) -> list[dict[str, Any]]:
    """Coincidencias por semana de las últimas ``semanas``, antiguas primero.

    El preview de hoy dice cuántos expedientes casan **ahora mismo** contra el
    corpus entero, que para una regla nueva es un número enorme e inútil: no
    responde a la pregunta que el usuario tiene, que es «¿cuánto correo me va a
    llegar por semana?». La serie sí.

    El recuento por semana lo hace Postgres (``db.repositories.watchlist_rules.
    weekly_match_counts``): traer una fila por coincidencia para contarlas aquí
    era un ``fetchall()`` sin techo justo en el caso para el que existe el
    preview —una regla amplia—. El ``iso_guard`` de las cláusulas deja fuera las
    filas legacy malformadas (v59), que es lo que permite castear la columna
    TEXT sin que una fecha en DD/MM/YYYY reviente la consulta.

    ADR-022: aquí se construyen las cláusulas; el SQL se ejecuta en ``db/``.
    """
    desde = (datetime.now(UTC) - timedelta(weeks=semanas)).date()
    clauses = [
        *_rule_clauses(rule),
        licitaciones.c.fecha_publicacion >= desde.isoformat(),
        licitaciones.c.fecha_publicacion < "3000",
    ]
    # El SQL agrupa por día (acotado por construcción); el lunes se calcula
    # aquí, que es aritmética y no necesita castear una columna TEXT.
    por_dia = daily_match_counts(clauses, desde_iso=desde.isoformat())
    por_semana: dict[str, int] = {}
    for texto, n in por_dia.items():
        try:
            dia = date.fromisoformat(texto)
        except ValueError:
            continue  # fila legacy malformada (v59): no cae en ninguna semana
        lunes = (dia - timedelta(days=dia.weekday())).isoformat()
        por_semana[lunes] = por_semana.get(lunes, 0) + n

    # Semanas completas y contiguas, incluidas las de cero. Una serie que sólo
    # trae las semanas con coincidencias se lee como constante: ocho puntos
    # seguidos de 40 cuando en realidad hubo 40 una semana y nada en siete.
    hoy = datetime.now(UTC).date()
    primer_lunes = hoy - timedelta(days=hoy.weekday() + 7 * (semanas - 1))
    serie: list[dict[str, Any]] = []
    for i in range(semanas):
        lunes = (primer_lunes + timedelta(weeks=i)).isoformat()
        serie.append({"semana": lunes, "n": por_semana.get(lunes, 0)})
    return serie


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
    return listar_matches(clauses, _MATCH_COLS, limit=limit)


def reglas_activas() -> list[WatchlistRule]:
    """Las reglas activas de todos los usuarios (barrido del job nocturno)."""
    return [_fila_a_regla(fila) for fila in filas_de_reglas_activas()]


def ids_abiertas_que_casan(
    reglas: Sequence[WatchlistRule] | None = None, *, hoy_iso: str | None = None
) -> list[str]:
    """``id_externo`` abiertos con plazo vigente que casan con alguna regla.

    Es la selección de D52 (plan 2026-10): la ficha del pliego nocturna va
    primero a lo que el resumen diario va a enseñar. Cada regla se evalúa con
    **su** predicado de siempre (:func:`_rule_clauses`, el mismo de la vista
    previa, el detalle y el job de alertas) acotado al universo «abierta con
    plazo vigente» (:func:`_clausulas_universo_puntuable`, la definición de
    ``mcp_server/glosario.md`` §3). Con ``banda_min`` se resuelve con
    :func:`_ids_desde_banda`, que ya trae ese universo.

    El techo por regla es :data:`MAX_CANDIDATAS_BANDA`: lo abierto con plazo
    son del orden de mil filas en total, así que no recorta en la práctica.

    Fail-open por regla: una regla que no se puede evaluar (un criterio
    corrupto, el scorer caído) se registra y se salta. Lo que está en juego es
    un orden, y perderlo para todas por una regla rota sería peor.
    """
    if reglas is None:
        reglas = reglas_activas()
    vistos: dict[str, None] = {}
    for regla in reglas:
        try:
            if regla.banda_min:
                ids = _ids_desde_banda(regla, hoy_iso=hoy_iso)
            else:
                ids = ids_que_casan(
                    [
                        *_rule_clauses(regla, hoy_iso=hoy_iso),
                        *_clausulas_universo_puntuable(hoy_iso),
                    ],
                    limit=MAX_CANDIDATAS_BANDA,
                )
        except Exception as exc:
            log.warning(
                "watchlist_rule_match_failed",
                rule_id=regla.id,
                error=str(exc),
                exc_info=True,
            )
            continue
        vistos.update(dict.fromkeys(ids))
    return list(vistos)


def matches_since(
    rule: WatchlistRule,
    since: str | None,
    *,
    limit: int = 50,
    user_key: str | None = None,
    user_id: int | None = None,
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
    ``user_id`` (v129) hace dual ese anti-join y no cambia nada más.
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
        user_id=user_id,
    )
