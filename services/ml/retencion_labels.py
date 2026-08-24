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

Antes de entrenar nada: auditar una muestra manual con
``python scripts/audit_retencion.py`` (acceptance: precisión del
emparejamiento ≥90% sobre 50 pares).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from db.contrato_eventos import contar_por_licitacion_y_tipo
from db.repositories.adjudicaciones import AdjudicacionRepository
from observability.logging import get_logger
from services.dedupe import normalize_organo
from services.ml.features import _cpv4, _fecha_dt

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

# Mínimo de pares observados para publicar la tasa de un segmento
# ``(órgano normalizado, CPV-4)``. Por debajo, el consumidor cae a su media
# global: con 1-2 pares la tasa es 0.0 o 1.0 por ruido de muestreo.
MIN_OBS_SEGMENTO = 5

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
    """Histórico ordenado por fecha de adjudicación (ver ``load_para_retencion``)."""
    return _adj_repo.load_para_retencion()


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

    importe = adj.get("importe")
    adjudicado = adj.get("importe_adjudicado")
    baja_original = (
        (float(importe) - float(adjudicado)) / float(importe)
        if importe and adjudicado and float(importe) > 0
        else None
    )
    antiguedad = (
        (ancla_dt - _fecha_dt(str(previos[0]["fecha_adjudicacion"]))).days / 30.0
        if previos
        else None
    )
    ev = eventos.get(str(adj["licitacion_id"]), {})
    return {
        "antiguedad_relacion_meses": antiguedad,
        "contratos_previos_organo": float(len(previos)),
        "cuota_segmento": importe_empresa / total_seg if total_seg > 0 else None,
        "hhi_segmento": hhi,
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
        empresa_id = adj.get("empresa_id")
        organo_n = normalize_organo(adj.get("organo"))
        cpv4 = _cpv4(adj.get("cpv"))
        if not fin or empresa_id is None or not organo_n or not cpv4:
            continue
        lic_id = str(adj["licitacion_id"])
        if lic_id in vistos:
            continue  # contratos multi-lote: un par por contrato
        fin_dt = _fecha_dt(str(fin))

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


def tasas_retencion_por_segmento(
    *,
    min_obs: int = MIN_OBS_SEGMENTO,
    ventana_meses: int = VENTANA_MESES,
    anticipacion_meses: int = VENTANA_ANTICIPACION_MESES,
) -> dict[tuple[str, str], float]:
    """Tasa de retención observada por ``(órgano normalizado, CPV-4)``.

    Es ``AVG(label)`` sobre los MISMOS pares vencimiento→sucesora que entrena
    el modelo: la fracción de vencimientos del segmento que el incumbente
    volvió a ganar. Los segmentos con menos de ``min_obs`` pares no se
    publican — el consumidor decide su fallback (``services.ml.scoring`` usa la
    media global).

    No calcula features a propósito: el baseline solo necesita etiquetas, y
    :func:`_features_historicas` recorre el histórico completo por par.
    """
    por_segmento: dict[tuple[str, str], list[int]] = defaultdict(list)
    for e in _emparejar(
        _cargar_adjudicaciones(),
        ventana_meses=ventana_meses,
        anticipacion_meses=anticipacion_meses,
    ):
        por_segmento[(e.organo_n, e.cpv4)].append(e.label)

    tasas = {
        clave: sum(labels) / len(labels)
        for clave, labels in por_segmento.items()
        if len(labels) >= min_obs
    }
    log.info(
        "retencion_tasas_segmento",
        segmentos=len(tasas),
        segmentos_descartados=len(por_segmento) - len(tasas),
        pares=sum(len(v) for v in por_segmento.values()),
    )
    return tasas


def features_para_vencimientos(*, months_ahead: int = 12) -> list[ParRetencion]:
    """Filas de scoring: contratos con empresa que vencen en los próximos N meses.

    Mismas features que el entrenamiento, calculadas con el histórico hasta
    hoy (en scoring no hay fuga: el sucesor aún no existe). ``label = -1`` y
    ``sucesor_id`` vacío marcan que es una fila de inferencia.
    """
    adjudicaciones = _cargar_adjudicaciones()
    eventos = _eventos_por_licitacion()
    hoy = datetime.now().strftime("%Y-%m-%d")
    limite = (_fecha_dt(hoy) + timedelta(days=months_ahead * 30)).strftime("%Y-%m-%d")

    filas: list[ParRetencion] = []
    vistos: set[str] = set()
    for adj in adjudicaciones:
        fin = adj.get("fecha_fin_efectiva")
        empresa_id = adj.get("empresa_id")
        organo_n = normalize_organo(adj.get("organo"))
        cpv4 = _cpv4(adj.get("cpv"))
        lic_id = str(adj["licitacion_id"])
        if (
            not fin
            or empresa_id is None
            or not organo_n
            or not cpv4
            or lic_id in vistos
            or not (hoy <= str(fin)[:10] <= limite)
        ):
            continue
        vistos.add(lic_id)
        filas.append(
            ParRetencion(
                licitacion_id=lic_id,
                sucesor_id="",
                empresa_id=int(empresa_id),
                organo=str(adj.get("organo")),
                fecha_fin=str(fin)[:10],
                fecha_sucesor="",
                label=-1,
                features=_features_historicas(
                    adjudicaciones,
                    eventos,
                    adj=adj,
                    ancla=hoy,
                    ancla_dt=_fecha_dt(hoy),
                    organo_n=organo_n,
                    cpv4=cpv4,
                    empresa_id=int(empresa_id),
                ),
                cpv4=cpv4,
                titulo_original=adj.get("titulo"),
                empresa_original=adj.get("nombre"),
            )
        )
    return filas


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
