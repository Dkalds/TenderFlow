"""Etiquetado de retención de renovaciones (Fase 6.2 v1, RFC 20260611-2).

El único evento con positivo Y negativo observables en nuestros datos es la
renovación: el incumbente de un contrato que vence vuelve a ganar el
siguiente análogo (positivo) o lo gana otro (negativo). No inventamos
negativos sintéticos — el modelo genérico empresa-licitación queda para v2.

Construcción de pares: contrato vencido (con empresa del maestro y fecha de
fin efectiva) → siguiente adjudicación del **mismo órgano normalizado** con
**mismo CPV-4** cuya fecha de adjudicación cae en la ventana
``[fin - VENTANA_ANTICIPACION_MESES, fin + VENTANA_MESES]``. Si hay varias
candidatas gana la más cercana al vencimiento. ``label = 1`` si la empresa
sucesora (vía maestro) es la misma.

Features anti-fuga: todas se calculan con adjudicaciones estrictamente
anteriores al **ancla** del par (antigüedad de la relación órgano-empresa, nº
de contratos previos, cuota en el segmento CPV-4, HHI del segmento, baja con
la que se ganó el original, y nº de modificaciones / prórrogas del original en
``contrato_eventos`` como proxy de satisfacción).

**El ancla no es el vencimiento**, es ``min(fin, fecha de adjudicación de la
sucesora)`` (:func:`_emparejar`). Cuando el órgano re-licita ANTES de que
venza el contrato —lo habitual en el sector público— la sucesora cumple
``fecha_adjudicacion < fin`` y, como comparte órgano normalizado y CPV-4 por
construcción, entraba en el histórico de sus propias features: ``contratos_
previos_organo`` valía +1 exactamente cuando ``label == 1``,
``antiguedad_relacion_meses`` se movía solo en los positivos y
``cuota_segmento`` sumaba el importe de la sucesora solo si la ganaba el
incumbente. Tres features que codificaban el target, y con ellas cualquier
métrica de validación medía la fuga en vez del modelo.

**Serving** (:func:`vencimientos_proximos`, :func:`vencimientos_con_features`).
La población que se puntúa —contratos con empresa que vencen dentro del
horizonte— y sus features son dos pasos. El baseline solo necesita la población
y su clave de segmento. Hasta 2026-09 las features se calculaban igual y se
tiraban, y eran el grueso del batch (~10 min 40 s de un step de 1.049 s el
2026-09-24): 3.003 contratos, y cada uno pasaba por
:func:`_features_historicas`, que recorre las ~698K adjudicaciones dos veces.
Ahora solo se calculan con modelo activo, desde un índice que se construye una
vez (:class:`_IndiceServing`).

Antes de entrenar nada: auditar una muestra manual con
``python scripts/audit_retencion.py`` (acceptance: precisión del
emparejamiento ≥90% sobre 50 pares).
"""

from __future__ import annotations

import calendar
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from db.contrato_eventos import contar_por_licitacion_y_tipo
from db.repositories.adjudicaciones import AdjudicacionRepository
from observability.logging import get_logger
from services.dedupe import normalize_organo
from services.ml.features import _cpv4, _fecha_dt, _fecha_opt

log = get_logger(__name__)

_adj_repo = AdjudicacionRepository()

# Ventana de emparejamiento vencimiento→sucesora. Es **asimétrica** a
# propósito, y hasta 2026-08 no lo era (±18 meses):
#
# - hacia adelante (18 meses) el margen absorbe la demora habitual entre el fin
#   de un contrato y la formalización del siguiente;
# - hacia atrás bastan 6. El sector público re-licita con antelación, pero una
#   adjudicación 18 meses ANTES del vencimiento no es la sucesora de ese
#   contrato: es otro contrato del mismo segmento vivo en paralelo. Admitirla
#   fabricaba pares que nunca existieron y, además, recortaba el ancla de las
#   features 18 meses (ver módulo), dejando al modelo sin histórico reciente
#   justo en los pares peor emparejados.
VENTANA_MESES = 18
VENTANA_ANTICIPACION_MESES = 6

# Mínimo de pares observados para publicar la tasa **cruda** de un segmento
# ``(órgano normalizado, CPV-4)`` en :func:`tasas_retencion_por_segmento`: con
# 1-2 pares la tasa es 0.0 o 1.0 por ruido de muestreo. El baseline de serving
# ya no corta por aquí: encoge cada segmento hacia su CPV-4 y este hacia la tasa
# global (``services.ml.scoring._baseline_retencion``), así que un segmento con
# un solo par aporta lo que vale un par en vez de nada.
MIN_OBS_SEGMENTO = 5

# Margen, en días, que la ventana de scoring suma por encima del horizonte
# (:func:`ventana_vencimientos`). La vista de Renovaciones recalcula su ventana
# en cada petición (``CURRENT_DATE``), pero el batch la fija una vez al día y el
# cron de Actions arranca con horas de retraso variable (entre las 08:05 y las
# 19:29 UTC con el mismo ``30 7 * * *``, 2026-08/09): sin margen, lo que entra
# por arriba en la vista entre una corrida y la siguiente se ve sin riesgo —NULL,
# score 0— hasta la noche siguiente. Siete días cubren además una semana de
# corridas fallidas; puntuar unos días de más no cuesta nada.
MARGEN_VENTANA_DIAS = 7

FEATURE_COLUMNS_RETENCION: tuple[str, ...] = (
    "antiguedad_relacion_meses",
    "contratos_previos_organo",
    "cuota_segmento",
    "hhi_segmento",
    "baja_original",
    "n_modificaciones",
    "n_prorrogas",
    "importe_original",
)


@dataclass
class ParRetencion:
    """Un par vencimiento→sucesor con label y features."""

    licitacion_id: str
    sucesor_id: str
    empresa_id: int
    organo: str
    fecha_fin: str
    fecha_sucesor: str
    label: int  # 1 = el incumbente retuvo el contrato
    features: dict[str, float | None]
    # CPV-4 del contrato. Es la mitad de la clave de segmento con la que se
    # agregan las tasas históricas (la otra es ``normalize_organo(organo)``);
    # sin él, el serving del baseline no podía mirar la tasa de su segmento.
    cpv4: str | None = None
    # Contexto para auditoría manual
    titulo_original: str | None = None
    titulo_sucesor: str | None = None
    empresa_original: str | None = None
    empresa_sucesora: str | None = None


@dataclass(frozen=True)
class _Emparejamiento:
    """Un vencimiento con su sucesora ya elegida, antes de calcular features.

    Es el resultado intermedio que comparten :func:`construir_pares` (que le
    añade las features) y :func:`tasas_retencion_por_segmento` (que solo
    necesita las etiquetas): el emparejamiento se implementa una vez.
    """

    adj: dict[str, Any]
    sucesora: dict[str, Any]
    licitacion_id: str
    sucesor_id: str
    empresa_id: int
    organo_n: str
    cpv4: str
    fin: str
    ancla: str
    ancla_dt: datetime
    label: int


def _cargar_adjudicaciones() -> list[dict[str, Any]]:
    """Histórico ordenado por fecha de adjudicación (ver ``load_para_retencion``).

    Descarta las filas con ``fecha_adjudicacion`` imposible. El resto del módulo
    la reparsea con ``_fecha_dt`` —el parser **estricto**— en cuatro sitios:
    antigüedad de la relación, los dos extremos de la ventana de sucesión y el
    ancla anti-fuga. Una sola fila basura tumba el entrenamiento entero, que es
    exactamente como murió el carril de baja el 2026-09-01.

    El #262 cerró aquel caso concreto filtrando los años de menos de cuatro
    cifras en ``_fecha_opt``, pero este módulo no pasaba por ese parser: llamaba
    a ``_fecha_dt`` sobre el TEXT crudo. Filtrando en la carga, los cuatro call
    sites quedan cubiertos a la vez.
    """
    filas = _adj_repo.load_para_retencion()
    validas = [f for f in filas if _fecha_opt(f.get("fecha_adjudicacion")) is not None]
    if len(validas) != len(filas):
        log.warning(
            "retencion_labels_adjudicaciones_con_fecha_imposible",
            descartadas=len(filas) - len(validas),
            total=len(filas),
        )
    return validas


def _eventos_por_licitacion() -> dict[str, dict[str, int]]:
    """Modificaciones y prórrogas por licitación, proxy de satisfacción."""
    return contar_por_licitacion_y_tipo()


def _features_historicas(
    adjudicaciones: list[dict[str, Any]],
    eventos: dict[str, dict[str, int]],
    *,
    adj: dict[str, Any],
    ancla: str,
    ancla_dt: datetime,
    organo_n: str,
    cpv4: str,
    empresa_id: int,
    excluir_licitaciones: frozenset[str] = frozenset(),
) -> dict[str, float | None]:
    """Features con histórico estrictamente anterior al ancla (anti-fuga).

    ``ancla`` es el instante desde el que se mira el pasado, en formato
    ``YYYY-MM-DD``: ``min(fin, adjudicación de la sucesora)`` al entrenar y
    "hoy" al servir. Se compara como texto contra ``fecha_adjudicacion``, que
    es TEXT y puede traer hora; recortar el ancla a la fecha hace que un
    contrato adjudicado **el mismo día** quede fuera (``"2025-06-01 09:00" <
    "2025-06-01"`` es falso). Es deliberado: el orden dentro del día no es
    observable, así que contarlo sería adivinar a favor del modelo.

    ``excluir_licitaciones`` saca del histórico expedientes concretos por id.
    Es la defensa en profundidad contra la fuga que motiva el ancla: la
    sucesora se excluye siempre, porque un expediente multi-lote tiene varias
    filas en ``adjudicaciones`` y a alguna podría corresponderle una fecha
    anterior al ancla.

    Es la implementación de **referencia**: el entrenamiento la llama par a par
    (cada par tiene su ancla y su sucesora excluida), y el índice de serving
    (:class:`_IndiceServing`) tiene que reproducir sus valores exactos con
    ``ancla = hoy`` y sin exclusiones. Recorre el histórico entero dos veces
    por llamada: aceptable al entrenar, cuadrático si se llama por fila al
    servir.
    """
    previos = [
        c
        for c in adjudicaciones
        if c.get("empresa_id") == empresa_id
        and normalize_organo(c.get("organo")) == organo_n
        and str(c["fecha_adjudicacion"]) < ancla
        and str(c["licitacion_id"]) not in excluir_licitaciones
    ]
    segmento_previo = [
        c
        for c in adjudicaciones
        if _cpv4(c.get("cpv")) == cpv4
        and str(c["fecha_adjudicacion"]) < ancla
        and str(c["licitacion_id"]) not in excluir_licitaciones
        and (c.get("importe_adjudicado") or 0) > 0
    ]
    total_seg = sum(float(c["importe_adjudicado"]) for c in segmento_previo)
    importe_empresa = sum(
        float(c["importe_adjudicado"]) for c in segmento_previo if c.get("empresa_id") == empresa_id
    )
    por_empresa: dict[Any, float] = defaultdict(float)
    for c in segmento_previo:
        por_empresa[c.get("empresa_id") or c.get("nombre")] += float(c["importe_adjudicado"])
    hhi = sum((v * 100.0 / total_seg) ** 2 for v in por_empresa.values()) if total_seg > 0 else None

    antiguedad = (
        (ancla_dt - _fecha_dt(str(previos[0]["fecha_adjudicacion"]))).days / 30.0
        if previos
        else None
    )
    return {
        "antiguedad_relacion_meses": antiguedad,
        "contratos_previos_organo": float(len(previos)),
        "cuota_segmento": importe_empresa / total_seg if total_seg > 0 else None,
        "hhi_segmento": hhi,
        **_features_del_contrato(adj, eventos),
    }


def _features_del_contrato(
    adj: dict[str, Any], eventos: dict[str, dict[str, int]]
) -> dict[str, float | None]:
    """Las features del propio contrato: baja, importe, modificaciones y prórrogas.

    No miran el histórico, así que no dependen del ancla: las comparten la
    referencia (:func:`_features_historicas`) y el índice de serving, que así
    no pueden divergir en ellas.
    """
    importe = adj.get("importe")
    adjudicado = adj.get("importe_adjudicado")
    baja_original = (
        (float(importe) - float(adjudicado)) / float(importe)
        if importe and adjudicado and float(importe) > 0
        else None
    )
    ev = eventos.get(str(adj["licitacion_id"]), {})
    return {
        "baja_original": baja_original,
        "n_modificaciones": float(ev.get("modificacion", 0)),
        "n_prorrogas": float(ev.get("prorroga", 0)),
        "importe_original": float(importe) if importe else None,
    }


def _emparejar(
    adjudicaciones: list[dict[str, Any]],
    *,
    ventana_meses: int = VENTANA_MESES,
    anticipacion_meses: int = VENTANA_ANTICIPACION_MESES,
) -> list[_Emparejamiento]:
    """Empareja cada vencimiento con su sucesora y calcula el ancla y el label.

    No toca las features: quien solo necesita etiquetas (el baseline de
    ``services.ml.scoring``) no puede pagar el coste de
    :func:`_features_historicas`, que recorre el histórico entero por par.
    """
    delta_post = timedelta(days=ventana_meses * 30)
    delta_pre = timedelta(days=anticipacion_meses * 30)

    # Índice de candidatas a sucesora por (órgano normalizado, CPV-4).
    por_segmento: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for adj in adjudicaciones:
        organo_n = normalize_organo(adj.get("organo"))
        cpv4 = _cpv4(adj.get("cpv"))
        if organo_n and cpv4:
            por_segmento[(organo_n, cpv4)].append(adj)

    emparejados: list[_Emparejamiento] = []
    vistos: set[str] = set()
    for adj in adjudicaciones:
        fin = adj.get("fecha_fin_efectiva")
        # `_fecha_opt` y no `_fecha_dt`: `fecha_fin_efectiva` es TEXT y admite
        # la misma basura que `fecha_adjudicacion`. Antes se comprobaba solo
        # que no fuese vacía y se parseaba a pelo más abajo, así que una fecha
        # imposible no se saltaba la fila: reventaba el batch.
        fin_dt = _fecha_opt(fin)
        empresa_id = adj.get("empresa_id")
        organo_n = normalize_organo(adj.get("organo"))
        cpv4 = _cpv4(adj.get("cpv"))
        if fin_dt is None or empresa_id is None or not organo_n or not cpv4:
            continue
        lic_id = str(adj["licitacion_id"])
        if lic_id in vistos:
            continue  # contratos multi-lote: un par por contrato

        candidatas = [
            c
            for c in por_segmento[(organo_n, cpv4)]
            if c["licitacion_id"] != adj["licitacion_id"]
            and str(c["fecha_adjudicacion"]) > str(adj["fecha_adjudicacion"])
            and -delta_pre <= _fecha_dt(str(c["fecha_adjudicacion"])) - fin_dt <= delta_post
        ]
        if not candidatas:
            continue
        sucesora = min(
            candidatas, key=lambda c: abs(_fecha_dt(str(c["fecha_adjudicacion"])) - fin_dt)
        )
        vistos.add(lic_id)

        # Ancla anti-fuga: en cuanto la sucesora existe, el pasado se corta ahí.
        ancla_dt = min(fin_dt, _fecha_dt(str(sucesora["fecha_adjudicacion"])))
        emparejados.append(
            _Emparejamiento(
                adj=adj,
                sucesora=sucesora,
                licitacion_id=lic_id,
                sucesor_id=str(sucesora["licitacion_id"]),
                empresa_id=int(empresa_id),
                organo_n=organo_n,
                cpv4=cpv4,
                fin=str(fin),
                ancla=ancla_dt.strftime("%Y-%m-%d"),
                ancla_dt=ancla_dt,
                label=1 if sucesora.get("empresa_id") == empresa_id else 0,
            )
        )
    return emparejados


def construir_pares(
    *,
    ventana_meses: int = VENTANA_MESES,
    anticipacion_meses: int = VENTANA_ANTICIPACION_MESES,
) -> list[ParRetencion]:
    """Pares etiquetados, en orden cronológico de vencimiento."""
    adjudicaciones = _cargar_adjudicaciones()
    eventos = _eventos_por_licitacion()

    pares: list[ParRetencion] = [
        ParRetencion(
            licitacion_id=e.licitacion_id,
            sucesor_id=e.sucesor_id,
            empresa_id=e.empresa_id,
            organo=str(e.adj.get("organo")),
            fecha_fin=e.fin[:10],
            fecha_sucesor=str(e.sucesora["fecha_adjudicacion"])[:10],
            label=e.label,
            features=_features_historicas(
                adjudicaciones,
                eventos,
                adj=e.adj,
                ancla=e.ancla,
                ancla_dt=e.ancla_dt,
                organo_n=e.organo_n,
                cpv4=e.cpv4,
                empresa_id=e.empresa_id,
                # El original NO se excluye: es un contrato previo real de la
                # relación órgano-empresa, conocido en el ancla, y su aporte es
                # el mismo en los pares con label 0 y con label 1 (lo fija
                # ``tests/test_ml_retencion.py::test_features_anti_fuga_y_
                # auditoria``). La sucesora sí, que es la que trae el target.
                excluir_licitaciones=frozenset({e.sucesor_id}),
            ),
            cpv4=e.cpv4,
            titulo_original=e.adj.get("titulo"),
            titulo_sucesor=e.sucesora.get("titulo"),
            empresa_original=e.adj.get("nombre"),
            empresa_sucesora=e.sucesora.get("nombre"),
        )
        for e in _emparejar(
            adjudicaciones,
            ventana_meses=ventana_meses,
            anticipacion_meses=anticipacion_meses,
        )
    ]

    pares.sort(key=lambda p: p.fecha_sucesor)
    log.info(
        "retencion_labels_built",
        pares=len(pares),
        positivos=sum(p.label for p in pares),
    )
    return pares


@dataclass(frozen=True)
class EtiquetasPorSegmento:
    """Lo que el serving necesita del emparejamiento, sacado de una sola pasada.

    ``conteos`` es ``(retenidos, pares)`` por ``(órgano normalizado, CPV-4)``
    sobre los MISMOS pares vencimiento→sucesora que entrena el modelo: la
    materia prima del baseline, que es quien decide cómo convertirla en tasa
    (``services.ml.scoring._baseline_retencion``).

    ``con_sucesora`` son los expedientes cuyo vencimiento ya tiene sucesora
    adjudicada según la misma heurística (:func:`_emparejar`). No se limita al
    pasado: un contrato que vence dentro de tres meses y cuyo segmento ya se
    re-licitó hace uno aparece aquí, y es justo el caso que el scoring tiene
    que reconocer entre sus vencimientos.
    """

    conteos: dict[tuple[str, str], tuple[int, int]]
    con_sucesora: frozenset[str]

    @property
    def pares(self) -> int:
        """Pares etiquetados en total, sumando todos los segmentos."""
        return sum(n for _, n in self.conteos.values())


def etiquetas_por_segmento(
    adjudicaciones: list[dict[str, Any]] | None = None,
    *,
    ventana_meses: int = VENTANA_MESES,
    anticipacion_meses: int = VENTANA_ANTICIPACION_MESES,
) -> EtiquetasPorSegmento:
    """Etiquetas agregadas por segmento y expedientes con sucesora, en una pasada.

    ``adjudicaciones`` permite pasar el histórico ya cargado: el scoring lo
    comparte con la población y las features. El 2026-09-24 la carga de las
    tasas repetía la de la población —las mismas 697.876 filas, ~1 min más—.
    Sin él se carga aquí.

    No calcula features a propósito: el baseline solo necesita etiquetas.
    """
    if adjudicaciones is None:
        adjudicaciones = _cargar_adjudicaciones()
    retenidos: Counter[tuple[str, str]] = Counter()
    pares: Counter[tuple[str, str]] = Counter()
    con_sucesora: set[str] = set()
    for e in _emparejar(
        adjudicaciones,
        ventana_meses=ventana_meses,
        anticipacion_meses=anticipacion_meses,
    ):
        clave = (e.organo_n, e.cpv4)
        retenidos[clave] += e.label
        pares[clave] += 1
        con_sucesora.add(e.licitacion_id)
    return EtiquetasPorSegmento(
        conteos={clave: (retenidos[clave], n) for clave, n in pares.items()},
        con_sucesora=frozenset(con_sucesora),
    )


def tasas_retencion_por_segmento(
    *,
    min_obs: int = MIN_OBS_SEGMENTO,
    ventana_meses: int = VENTANA_MESES,
    anticipacion_meses: int = VENTANA_ANTICIPACION_MESES,
    adjudicaciones: list[dict[str, Any]] | None = None,
) -> dict[tuple[str, str], float]:
    """Tasa de retención **cruda** por ``(órgano normalizado, CPV-4)``.

    ``AVG(label)`` de cada segmento con al menos ``min_obs`` pares: la fracción
    de vencimientos que el incumbente volvió a ganar. Es la lectura de
    diagnóstico. El serving la usó hasta 2026-09, con los segmentos por debajo
    de ``min_obs`` cayendo a la media NO ponderada de las tasas publicadas (el
    2026-09-24, 1.076 segmentos descartados frente a 208 publicados); ahora
    usa el shrinkage jerárquico de ``services.ml.scoring._baseline_retencion``
    sobre :func:`etiquetas_por_segmento`.
    """
    etiquetas = etiquetas_por_segmento(
        adjudicaciones,
        ventana_meses=ventana_meses,
        anticipacion_meses=anticipacion_meses,
    )
    tasas = {
        clave: retenidos / pares
        for clave, (retenidos, pares) in etiquetas.conteos.items()
        if pares >= min_obs
    }
    log.info(
        "retencion_tasas_segmento",
        segmentos=len(tasas),
        segmentos_descartados=len(etiquetas.conteos) - len(tasas),
        pares=etiquetas.pares,
    )
    return tasas


# ── Serving: población y features de los vencimientos próximos ──────────────


def _hoy_iso(hoy: str | None = None) -> str:
    """``hoy`` normalizado a ``YYYY-MM-DD``; la fecha local de hoy si no se pasa.

    Es a la vez el borde inferior de la ventana y el ancla de las features de
    serving, que se compara **como texto** contra ``fecha_adjudicacion``: por
    eso se normaliza, porque ``"2026-09-24 00:00"`` y ``"2026-09-24"`` no
    cortan igual.
    """
    return _fecha_dt(hoy).strftime("%Y-%m-%d") if hoy else datetime.now().strftime("%Y-%m-%d")


def _sumar_meses(base: date, meses: int) -> date:
    """``base + meses`` con la aritmética de ``date + N * INTERVAL '1 month'``.

    Meses de calendario y, si el día no existe en el mes de destino, el último
    del mes (31-ene + 1 mes = 28 o 29-feb), que es lo que hace Postgres.
    """
    indice = base.month - 1 + meses
    anio, mes = base.year + indice // 12, indice % 12 + 1
    return date(anio, mes, min(base.day, calendar.monthrange(anio, mes)[1]))


def ventana_vencimientos(months_ahead: int, *, hoy: str | None = None) -> tuple[str, str]:
    """``(desde, hasta)`` de los vencimientos que puntúa el batch, en ``YYYY-MM-DD``.

    Espejo de ``db.repositories.renovaciones.rango_vencimiento_sql()``, que es
    lo que filtra la vista: hoy, y hoy más ``months_ahead`` meses **de
    calendario**, más :data:`MARGEN_VENTANA_DIAS`. Hasta 2026-09 aquí se
    sumaban meses de 30 días: 12 meses eran 360 días, y los contratos que
    vencían en los últimos cinco o seis días del año que enseña la vista salían
    sin riesgo. Con el margen, todo contrato visible en la vista con ``months <=
    months_ahead`` cae dentro, con la misma comparación de texto sobre la misma
    fecha de fin (``fecha_fin_sql``).

    Supone que ``CURRENT_DATE`` en la BD y la fecha local del batch coinciden
    (UTC los dos por defecto: Postgres gestionado y runners de Actions). Un
    desfase de un día hacia delante lo absorbe el margen; uno hacia atrás
    dejaría sin puntuar, ese día, los contratos que vencen ese mismo día.
    """
    base = _fecha_dt(_hoy_iso(hoy)).date()
    hasta = _sumar_meses(base, months_ahead) + timedelta(days=MARGEN_VENTANA_DIAS)
    return base.isoformat(), hasta.isoformat()


@dataclass(frozen=True)
class _Vencimiento:
    """Un contrato de la población de scoring, con la fila de la que sale.

    La fila hace falta para las features del propio contrato (baja, importe,
    eventos) y la clave normalizada para buscar su histórico en el índice;
    ninguna de las dos viaja en :class:`ParRetencion`.
    """

    adj: dict[str, Any]
    licitacion_id: str
    empresa_id: int
    organo_n: str
    cpv4: str
    fin: str

    def par(self, features: dict[str, float | None]) -> ParRetencion:
        """Fila de inferencia: ``label = -1`` y ``sucesor_id`` vacío la marcan."""
        return ParRetencion(
            licitacion_id=self.licitacion_id,
            sucesor_id="",
            empresa_id=self.empresa_id,
            organo=str(self.adj.get("organo")),
            fecha_fin=self.fin,
            fecha_sucesor="",
            label=-1,
            features=features,
            cpv4=self.cpv4,
            titulo_original=self.adj.get("titulo"),
            empresa_original=self.adj.get("nombre"),
        )


def _vencimientos(
    adjudicaciones: list[dict[str, Any]], *, desde: str, hasta: str
) -> list[_Vencimiento]:
    """Contratos con empresa cuyo fin cae en ``[desde, hasta]``, uno por expediente.

    Es el filtro que aplicaba ``features_para_vencimientos`` antes de separar
    población y features, sin cambios: fin efectivo (como texto) dentro de la
    ventana, ``empresa_id``, órgano normalizado y CPV-4 válido, y del
    expediente multi-lote la **primera fila que pasa** en el orden cronológico
    de la carga. Las condiciones baratas van primero para no normalizar el
    órgano de las ~698K filas cuando solo unas miles caen en la ventana; el
    orden de las comprobaciones no cambia qué filas pasan.
    """
    vencimientos: list[_Vencimiento] = []
    vistos: set[str] = set()
    for adj in adjudicaciones:
        fin = adj.get("fecha_fin_efectiva")
        empresa_id = adj.get("empresa_id")
        if not fin or empresa_id is None or not (desde <= str(fin)[:10] <= hasta):
            continue
        lic_id = str(adj["licitacion_id"])
        if lic_id in vistos:
            continue
        organo_n = normalize_organo(adj.get("organo"))
        cpv4 = _cpv4(adj.get("cpv"))
        if not organo_n or not cpv4:
            continue
        vistos.add(lic_id)
        vencimientos.append(
            _Vencimiento(
                adj=adj,
                licitacion_id=lic_id,
                empresa_id=int(empresa_id),
                organo_n=organo_n,
                cpv4=cpv4,
                fin=str(fin)[:10],
            )
        )
    return vencimientos


def _acumulado_vacio() -> defaultdict[object, float]:
    """Acumulador de importe por empresa de un segmento (base del HHI)."""
    return defaultdict(float)


class _IndiceServing:
    """El histórico anterior al ancla, indexado una vez para toda la población.

    :func:`_features_historicas` filtra el histórico entero dos veces por
    contrato. Al servir no hace falta: todas las filas comparten el ancla (hoy)
    y no excluyen nada, así que «lo anterior al ancla» es lo mismo para todas.
    Aquí se recorre una vez y se guarda solo lo que la población va a pedir:
    por ``(empresa, órgano normalizado)``, el primer contrato previo y cuántos
    hay; por CPV-4, los importes previos (el total, y los de cada empresa para
    la cuota) y el acumulado por empresa con el que se calcula el HHI.

    Tiene que dar EXACTAMENTE los valores de la referencia, y lo fija
    ``tests/test_ml_retencion_serving.py``: la misma comparación de texto
    contra el ancla, las filas en el mismo orden y la misma ``sum()`` sobre la
    misma secuencia de importes. Lo último no es pedantería: desde Python 3.12
    ``sum()`` de floats es compensada, así que acumular a mano con ``+=`` daría
    otro último bit, y el modelo recibiría features distintas de las que se
    validaron. El acumulado del HHI sí es un ``+=`` porque así lo hace la
    referencia.
    """

    def __init__(
        self,
        adjudicaciones: list[dict[str, Any]],
        vencimientos: list[_Vencimiento],
        *,
        ancla: str,
    ) -> None:
        self._ancla_dt = _fecha_dt(ancla)
        empresas = {v.empresa_id for v in vencimientos}
        relaciones = {(v.empresa_id, v.organo_n) for v in vencimientos}
        segmentos = {v.cpv4 for v in vencimientos}
        cuotas = {(v.cpv4, v.empresa_id) for v in vencimientos}

        # Las claves llevan el ``empresa_id`` crudo de la fila —``object``: la
        # fila llega de la BD sin tipar— y así el lookup con el entero de la
        # población iguala con el mismo ``==`` que la referencia.
        self._primer_contrato: dict[tuple[object, str | None], str] = {}
        self._contratos_previos: Counter[tuple[object, str | None]] = Counter()
        self._importes: defaultdict[str, list[float]] = defaultdict(list)
        self._importes_empresa: defaultdict[tuple[str, object], list[float]] = defaultdict(list)
        self._acumulado_hhi: defaultdict[str, defaultdict[object, float]] = defaultdict(
            _acumulado_vacio
        )
        self._por_segmento: dict[str, tuple[float, float | None]] = {}
        # ``normalize_organo`` son varias pasadas de regex y el mismo órgano se
        # repite en miles de filas: se normaliza una vez por texto crudo.
        organos: dict[object, str | None] = {}

        for c in adjudicaciones:
            empresa = c.get("empresa_id")
            if empresa in empresas:
                organo = c.get("organo")
                if organo not in organos:
                    organos[organo] = normalize_organo(organo)
                relacion = (empresa, organos[organo])
                if relacion in relaciones and str(c["fecha_adjudicacion"]) < ancla:
                    self._primer_contrato.setdefault(relacion, str(c["fecha_adjudicacion"]))
                    self._contratos_previos[relacion] += 1
            cpv4 = _cpv4(c.get("cpv"))
            if (
                cpv4 is not None
                and cpv4 in segmentos
                and str(c["fecha_adjudicacion"]) < ancla
                and (c.get("importe_adjudicado") or 0) > 0
            ):
                importe = float(c["importe_adjudicado"])
                self._importes[cpv4].append(importe)
                if (cpv4, empresa) in cuotas:
                    self._importes_empresa[(cpv4, empresa)].append(importe)
                self._acumulado_hhi[cpv4][empresa or c.get("nombre")] += importe

    def features(
        self, v: _Vencimiento, eventos: dict[str, dict[str, int]]
    ) -> dict[str, float | None]:
        """Lo que daría :func:`_features_historicas` con ``ancla = hoy`` y sin exclusiones."""
        relacion = (v.empresa_id, v.organo_n)
        primero = self._primer_contrato.get(relacion)
        total_seg, hhi = self._segmento(v.cpv4)
        importe_empresa = sum(self._importes_empresa.get((v.cpv4, v.empresa_id), []))
        return {
            "antiguedad_relacion_meses": (
                (self._ancla_dt - _fecha_dt(primero)).days / 30.0 if primero is not None else None
            ),
            "contratos_previos_organo": float(self._contratos_previos[relacion]),
            "cuota_segmento": importe_empresa / total_seg if total_seg > 0 else None,
            "hhi_segmento": hhi,
            **_features_del_contrato(v.adj, eventos),
        }

    def _segmento(self, cpv4: str) -> tuple[float, float | None]:
        """``(total, HHI)`` de lo adjudicado antes del ancla en el CPV-4, una vez."""
        if cpv4 not in self._por_segmento:
            total = sum(self._importes.get(cpv4, []))
            hhi = (
                sum((x * 100.0 / total) ** 2 for x in self._acumulado_hhi[cpv4].values())
                if total > 0
                else None
            )
            self._por_segmento[cpv4] = (total, hhi)
        return self._por_segmento[cpv4]


def vencimientos_proximos(
    adjudicaciones: list[dict[str, Any]], *, months_ahead: int, hoy: str | None = None
) -> list[ParRetencion]:
    """Población de scoring **sin features**: lo único que necesita el baseline.

    Contratos con empresa que vencen dentro de :func:`ventana_vencimientos`,
    uno por expediente, con ``features={}``. El baseline solo mira ``organo``
    y ``cpv4``, su clave de segmento: calcular aquí las features para tirarlas
    era el grueso del batch (ver el docstring del módulo).
    """
    desde, hasta = ventana_vencimientos(months_ahead, hoy=hoy)
    return [v.par({}) for v in _vencimientos(adjudicaciones, desde=desde, hasta=hasta)]


def vencimientos_con_features(
    adjudicaciones: list[dict[str, Any]],
    *,
    months_ahead: int,
    hoy: str | None = None,
    eventos: dict[str, dict[str, int]] | None = None,
) -> list[ParRetencion]:
    """La población de :func:`vencimientos_proximos` con las features del modelo.

    Mismas features que el entrenamiento, con el histórico anterior a hoy (al
    servir no hay fuga: la sucesora aún no existe), y los mismos valores
    exactos que daría :func:`_features_historicas`, pero desde un índice que
    recorre el histórico una sola vez (:class:`_IndiceServing`). ``eventos``
    se carga aquí si no se pasa, y solo si hay algún vencimiento que puntuar.
    """
    ancla = _hoy_iso(hoy)
    desde, hasta = ventana_vencimientos(months_ahead, hoy=ancla)
    vencimientos = _vencimientos(adjudicaciones, desde=desde, hasta=hasta)
    if not vencimientos:
        return []
    if eventos is None:
        eventos = _eventos_por_licitacion()
    indice = _IndiceServing(adjudicaciones, vencimientos, ancla=ancla)
    return [v.par(indice.features(v, eventos)) for v in vencimientos]


def features_para_vencimientos(*, months_ahead: int = 12) -> list[ParRetencion]:
    """Filas de scoring con features: contratos con empresa que vencen en N meses.

    Compatibilidad: carga el histórico y los eventos y delega en
    :func:`vencimientos_con_features`. El batch ya no pasa por aquí: comparte
    una sola carga del histórico entre población, tasas y features
    (``services.ml.scoring.score_predicciones_retencion``).
    """
    adjudicaciones = _cargar_adjudicaciones()
    eventos = _eventos_por_licitacion()
    return vencimientos_con_features(adjudicaciones, months_ahead=months_ahead, eventos=eventos)


def muestra_auditoria(n: int = 50) -> list[dict[str, Any]]:
    """Muestra determinista para la auditoría manual previa al entrenamiento."""
    pares = construir_pares()
    paso = max(1, len(pares) // n)
    return [
        {
            "original": p.licitacion_id,
            "titulo_original": p.titulo_original,
            "empresa_original": p.empresa_original,
            "sucesor": p.sucesor_id,
            "titulo_sucesor": p.titulo_sucesor,
            "empresa_sucesora": p.empresa_sucesora,
            "fecha_fin": p.fecha_fin,
            "fecha_sucesor": p.fecha_sucesor,
            "label": p.label,
        }
        for p in pares[::paso][:n]
    ]
