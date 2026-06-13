"""Etiquetado de retención de renovaciones (Fase 6.2 v1, RFC 20260611-2).

El único evento con positivo Y negativo observables en nuestros datos es la
renovación: el incumbente de un contrato que vence vuelve a ganar el
siguiente análogo (positivo) o lo gana otro (negativo). No inventamos
negativos sintéticos — el modelo genérico empresa-licitación queda para v2.

Construcción de pares: contrato vencido (con empresa del maestro y fecha de
fin efectiva) → siguiente adjudicación del **mismo órgano normalizado** con
**mismo CPV-4** cuya fecha de adjudicación cae en la ventana de ±18 meses
alrededor del vencimiento. Si hay varias candidatas gana la más cercana al
vencimiento. ``label = 1`` si la empresa sucesora (vía maestro) es la misma.

Features anti-fuga: todas se calculan con adjudicaciones estrictamente
anteriores al vencimiento del contrato original (antigüedad de la relación
órgano-empresa, nº de contratos previos, cuota en el segmento CPV-4, HHI del
segmento, baja con la que se ganó el original, y nº de modificaciones /
prórrogas del original en ``contrato_eventos`` como proxy de satisfacción).

Antes de entrenar nada: auditar una muestra manual con
``python scripts/audit_retencion.py`` (acceptance: precisión del
emparejamiento ≥90% sobre 50 pares).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger
from services.competitive.renovaciones import _FECHA_FIN_SQL
from services.dedupe import exclude_duplicados_sql, normalize_organo
from services.ml.features import _cpv4, _fecha_dt

log = get_logger(__name__)

VENTANA_MESES = 18

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
    # Contexto para auditoría manual
    titulo_original: str | None = None
    titulo_sucesor: str | None = None
    empresa_original: str | None = None
    empresa_sucesora: str | None = None


def _cargar_adjudicaciones() -> list[dict[str, Any]]:
    sql = f"""
        SELECT a.licitacion_id, a.empresa_id, a.nombre, a.fecha_adjudicacion,
               a.importe_adjudicado, l.organo_contratacion AS organo, l.cpv,
               l.ccaa, l.importe, l.titulo,
               {_FECHA_FIN_SQL} AS fecha_fin_efectiva
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        WHERE a.fecha_adjudicacion IS NOT NULL AND {exclude_duplicados_sql()}
        ORDER BY a.fecha_adjudicacion ASC
    """  # noqa: S608 — fragmentos constantes (_FECHA_FIN_SQL, dedupe)
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql))


def _eventos_por_licitacion() -> dict[str, dict[str, int]]:
    with connect_read() as c:
        rows = rows_to_dicts(
            c.execute(
                "SELECT licitacion_id, tipo, COUNT(*) AS n FROM contrato_eventos "
                "WHERE tipo IN ('modificacion', 'prorroga') GROUP BY licitacion_id, tipo"
            )
        )
    out: dict[str, dict[str, int]] = defaultdict(dict)
    for r in rows:
        out[str(r["licitacion_id"])][str(r["tipo"])] = int(r["n"])
    return out


def _features_historicas(
    adjudicaciones: list[dict[str, Any]],
    eventos: dict[str, dict[str, int]],
    *,
    adj: dict[str, Any],
    fin: str,
    fin_dt: Any,
    organo_n: str,
    cpv4: str,
    empresa_id: int,
) -> dict[str, float | None]:
    """Features con histórico estrictamente anterior al vencimiento (anti-fuga)."""
    previos = [
        c
        for c in adjudicaciones
        if c.get("empresa_id") == empresa_id
        and normalize_organo(c.get("organo")) == organo_n
        and str(c["fecha_adjudicacion"]) < fin
    ]
    segmento_previo = [
        c
        for c in adjudicaciones
        if _cpv4(c.get("cpv")) == cpv4
        and str(c["fecha_adjudicacion"]) < fin
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
        (fin_dt - _fecha_dt(str(previos[0]["fecha_adjudicacion"]))).days / 30.0 if previos else None
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


def construir_pares(*, ventana_meses: int = VENTANA_MESES) -> list[ParRetencion]:
    """Pares etiquetados, en orden cronológico de vencimiento."""
    adjudicaciones = _cargar_adjudicaciones()
    eventos = _eventos_por_licitacion()
    delta = timedelta(days=ventana_meses * 30)

    # Índice de candidatas a sucesora por (órgano normalizado, CPV-4),
    # y de histórico por empresa/segmento para las features.
    por_segmento: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for adj in adjudicaciones:
        organo_n = normalize_organo(adj.get("organo"))
        cpv4 = _cpv4(adj.get("cpv"))
        if organo_n and cpv4:
            por_segmento[(organo_n, cpv4)].append(adj)

    pares: list[ParRetencion] = []
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
            and abs(_fecha_dt(str(c["fecha_adjudicacion"])) - fin_dt) <= delta
        ]
        if not candidatas:
            continue
        sucesora = min(
            candidatas, key=lambda c: abs(_fecha_dt(str(c["fecha_adjudicacion"])) - fin_dt)
        )
        vistos.add(lic_id)

        pares.append(
            ParRetencion(
                licitacion_id=lic_id,
                sucesor_id=str(sucesora["licitacion_id"]),
                empresa_id=int(empresa_id),
                organo=str(adj.get("organo")),
                fecha_fin=str(fin)[:10],
                fecha_sucesor=str(sucesora["fecha_adjudicacion"])[:10],
                label=1 if sucesora.get("empresa_id") == empresa_id else 0,
                features=_features_historicas(
                    adjudicaciones,
                    eventos,
                    adj=adj,
                    fin=str(fin),
                    fin_dt=fin_dt,
                    organo_n=organo_n,
                    cpv4=cpv4,
                    empresa_id=empresa_id,
                ),
                titulo_original=adj.get("titulo"),
                titulo_sucesor=sucesora.get("titulo"),
                empresa_original=adj.get("nombre"),
                empresa_sucesora=sucesora.get("nombre"),
            )
        )

    pares.sort(key=lambda p: p.fecha_sucesor)
    log.info(
        "retencion_labels_built",
        pares=len(pares),
        positivos=sum(p.label for p in pares),
    )
    return pares


def features_para_vencimientos(*, months_ahead: int = 12) -> list[ParRetencion]:
    """Filas de scoring: contratos con empresa que vencen en los próximos N meses.

    Mismas features que el entrenamiento, calculadas con el histórico hasta
    hoy (en scoring no hay fuga: el sucesor aún no existe). ``label = -1`` y
    ``sucesor_id`` vacío marcan que es una fila de inferencia.
    """
    from datetime import datetime

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
                    fin=hoy,
                    fin_dt=_fecha_dt(hoy),
                    organo_n=organo_n,
                    cpv4=cpv4,
                    empresa_id=int(empresa_id),
                ),
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
