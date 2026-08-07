"""Extracción de features para los modelos predictivos (Fase 6, RFC 20260611-2).

La pieza crítica es la **ausencia de fuga temporal**: el dataset se construye
recorriendo los pares válidos presupuesto/adjudicado en orden cronológico, y
las features históricas de cada fila (baja media del órgano, del CPV-4 y del
par organo-CPV en los 24 meses previos; HHI del segmento CPV-4/CCAA) se
calculan **antes** de incorporar esa fila a los acumuladores. Una fila nunca
ve datos de su propia fecha ni posteriores — anti-fuga por construcción, no
por filtrado a posteriori.

Diferencia documentada respecto al RFC: el HHI del segmento usa ventana
expansiva (todo el histórico estricto anterior a la fecha) en lugar de 24
meses móviles — misma garantía anti-fuga, coste O(1) por fila.

Sin dependencias nuevas: dict/deque de stdlib; numpy solo aparece en los
módulos de modelo.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from services.dedupe import exclude_duplicados_sql
from services.sql_fragments import EFFECTIVE_BUDGET_SQL, VALID_PAIR_LOTE
from shared.estados import ESTADOS_CERRADOS

# Bandas de importe con cortes en los umbrales SARA habituales (€, sin IVA).
_BANDAS_IMPORTE = (15_000.0, 60_000.0, 143_000.0, 221_000.0, 750_000.0, 5_538_000.0)

# Ventana de los agregados históricos de baja.
_VENTANA_MESES = 24

# Orden canónico de columnas del dataset (el modelo depende de él).
FEATURE_COLUMNS: tuple[str, ...] = (
    # categóricas
    "cpv2",
    "cpv4",
    "tipo_contrato",
    "ccaa",
    "fuente",
    "banda_importe",
    # numéricas (NaN permitido — HistGradientBoosting lo maneja nativo)
    "log_importe",
    "n_ofertas",
    "baja_media_organo",
    "baja_media_cpv4",
    "baja_media_organo_cpv4",
    "hhi_segmento",
    "mes",
    "trimestre",
)
CATEGORICAL_COLUMNS: tuple[str, ...] = FEATURE_COLUMNS[:6]


@dataclass
class FilaDataset:
    """Una observación: features + target (None en filas de scoring)."""

    licitacion_id: str
    fecha: str
    features: dict[str, Any]
    baja: float | None = None


def _banda_importe(importe: float | None) -> str:
    if not importe or importe <= 0:
        return "b_na"
    for i, corte in enumerate(_BANDAS_IMPORTE):
        if importe < corte:
            return f"b{i}"
    return f"b{len(_BANDAS_IMPORTE)}"


def _cpv4(cpv: str | None) -> str | None:
    digits = (cpv or "").strip()[:4]
    return digits if len(digits) == 4 and digits.isdigit() else None


def _fecha_dt(fecha: str) -> datetime:
    return datetime.strptime(fecha[:10], "%Y-%m-%d")


class _MediaMovil:
    """Media móvil de bajas por clave con ventana temporal (24 meses)."""

    def __init__(self, meses: int = _VENTANA_MESES) -> None:
        self._delta = timedelta(days=meses * 30)
        self._colas: dict[str, deque[tuple[datetime, float]]] = defaultdict(deque)
        self._sumas: dict[str, float] = defaultdict(float)

    def media(self, clave: str | None, fecha: datetime) -> float | None:
        if clave is None:
            return None
        cola = self._colas[clave]
        limite = fecha - self._delta
        while cola and cola[0][0] < limite:
            vieja = cola.popleft()
            self._sumas[clave] -= vieja[1]
        if not cola:
            return None
        return self._sumas[clave] / len(cola)

    def agregar(self, clave: str | None, fecha: datetime, baja: float) -> None:
        if clave is None:
            return
        self._colas[clave].append((fecha, baja))
        self._sumas[clave] += baja


class _HhiExpansivo:
    """HHI por segmento sobre todo el histórico estricto anterior."""

    def __init__(self) -> None:
        self._importes: dict[str, dict[Any, float]] = defaultdict(lambda: defaultdict(float))
        self._totales: dict[str, float] = defaultdict(float)

    def hhi(self, segmento: str | None) -> float | None:
        if segmento is None:
            return None
        total = self._totales.get(segmento) or 0.0
        if total <= 0:
            return None
        return sum((importe * 100.0 / total) ** 2 for importe in self._importes[segmento].values())

    def agregar(self, segmento: str | None, empresa: Any, importe: float | None) -> None:
        if segmento is None or not importe or importe <= 0:
            return
        self._importes[segmento][empresa] += importe
        self._totales[segmento] += importe


@dataclass
class _Acumuladores:
    """Estado histórico compartido entre dataset de entrenamiento y scoring."""

    por_organo: _MediaMovil = field(default_factory=_MediaMovil)
    por_cpv4: _MediaMovil = field(default_factory=_MediaMovil)
    por_organo_cpv4: _MediaMovil = field(default_factory=_MediaMovil)
    hhi: _HhiExpansivo = field(default_factory=_HhiExpansivo)

    def features_historicas(
        self, *, organo: str | None, cpv4: str | None, ccaa: str | None, fecha: datetime
    ) -> dict[str, float | None]:
        clave_oc = f"{organo}|{cpv4}" if organo and cpv4 else None
        segmento = f"{cpv4}|{ccaa}" if cpv4 and ccaa else None
        return {
            "baja_media_organo": self.por_organo.media(organo, fecha),
            "baja_media_cpv4": self.por_cpv4.media(cpv4, fecha),
            "baja_media_organo_cpv4": self.por_organo_cpv4.media(clave_oc, fecha),
            "hhi_segmento": self.hhi.hhi(segmento),
        }

    def incorporar(
        self,
        *,
        organo: str | None,
        cpv4: str | None,
        ccaa: str | None,
        empresa: Any,
        fecha: datetime,
        baja: float,
        importe_adjudicado: float | None,
    ) -> None:
        self.por_organo.agregar(organo, fecha, baja)
        self.por_cpv4.agregar(cpv4, fecha, baja)
        if organo and cpv4:
            self.por_organo_cpv4.agregar(f"{organo}|{cpv4}", fecha, baja)
        if cpv4 and ccaa:
            self.hhi.agregar(f"{cpv4}|{ccaa}", empresa, importe_adjudicado)


def _features_estaticas(row: dict[str, Any], fecha: datetime) -> dict[str, Any]:
    importe = row.get("importe")
    cpv = row.get("cpv")
    n_ofertas = row.get("n_ofertas_recibidas")
    return {
        "cpv2": (cpv or "")[:2] or "na",
        "cpv4": _cpv4(cpv) or "na",
        "tipo_contrato": row.get("tipo_contrato") or "na",
        "ccaa": row.get("ccaa") or "na",
        "fuente": row.get("fuente") or "placsp",
        "banda_importe": _banda_importe(importe),
        "log_importe": math.log1p(importe) if importe and importe > 0 else None,
        "n_ofertas": float(n_ofertas) if n_ofertas is not None else None,
        "mes": float(fecha.month),
        "trimestre": float((fecha.month - 1) // 3 + 1),
    }


def _cargar_pares(hasta: str | None = None) -> list[dict[str, Any]]:
    sql = f"""
        SELECT l.id_externo, a.fecha_adjudicacion AS fecha, l.organo_contratacion AS organo,
               l.cpv, l.ccaa, l.tipo_contrato, l.fuente, l.importe,
               {EFFECTIVE_BUDGET_SQL} AS presupuesto_efectivo,
               a.importe_adjudicado, a.n_ofertas_recibidas, a.empresa_id, a.nombre
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        LEFT JOIN lotes lo ON lo.id = a.lote_id
        WHERE {VALID_PAIR_LOTE} AND a.fecha_adjudicacion IS NOT NULL
          AND COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed'
          AND {exclude_duplicados_sql()}
    """  # noqa: S608 — fragmentos constantes (VALID_PAIR_LOTE, EFFECTIVE_BUDGET_SQL, dedupe); valores con ?
    params: list[Any] = []
    if hasta:
        sql += " AND a.fecha_adjudicacion <= %s"
        params.append(hasta)
    sql += " ORDER BY a.fecha_adjudicacion ASC, l.id_externo ASC"
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, params))


def construir_dataset_baja(
    hasta: str | None = None,
) -> tuple[list[FilaDataset], _Acumuladores]:
    """Dataset de entrenamiento del modelo de baja, en orden cronológico.

    Devuelve también los acumuladores ya cargados con todo el histórico
    procesado, listos para puntuar licitaciones abiertas con el mismo estado.
    """
    acum = _Acumuladores()
    filas: list[FilaDataset] = []
    for row in _cargar_pares(hasta):
        fecha = _fecha_dt(str(row["fecha"]))
        organo = row.get("organo")
        cpv4 = _cpv4(row.get("cpv"))
        ccaa = row.get("ccaa")
        # Baja contra el presupuesto REAL de la fila (el del lote si lo tiene,
        # v65_lotes), no contra ``l.importe`` del expediente completo: un lote al
        # 25% del expediente daba target 0.75 en vez de ~0.05 en cualquier
        # licitación multi-lote, corrompiendo el objetivo del modelo justo donde
        # más importa. Coherente con VALID_PAIR_LOTE del WHERE (comparación por
        # fila, no agregada por licitación).
        presupuesto = float(row["presupuesto_efectivo"])
        baja = (presupuesto - float(row["importe_adjudicado"])) / presupuesto

        features = _features_estaticas(row, fecha)
        features.update(acum.features_historicas(organo=organo, cpv4=cpv4, ccaa=ccaa, fecha=fecha))
        filas.append(
            FilaDataset(
                licitacion_id=str(row["id_externo"]),
                fecha=str(row["fecha"])[:10],
                features=features,
                baja=baja,
            )
        )
        # La fila entra en los acumuladores DESPUÉS de extraer sus features:
        # ninguna observación ve su propio resultado ni los posteriores.
        acum.incorporar(
            organo=organo,
            cpv4=cpv4,
            ccaa=ccaa,
            empresa=row.get("empresa_id") or row.get("nombre"),
            fecha=fecha,
            baja=baja,
            importe_adjudicado=float(row["importe_adjudicado"]),
        )
    return filas, acum


def features_licitaciones_abiertas(
    *, ahora: str | None = None, limit: int = 5000
) -> list[FilaDataset]:
    """Features de scoring para licitaciones sin adjudicación (batch nocturno).

    Los agregados históricos se construyen con TODO el histórico disponible
    (cutoff = hoy): en scoring no hay fuga porque el resultado aún no existe.
    """
    _, acum = construir_dataset_baja(hasta=ahora)
    fecha_score = _fecha_dt(ahora) if ahora else datetime.now()
    cerrados = ", ".join(["%s"] * len(ESTADOS_CERRADOS))
    sql = f"""
        SELECT l.id_externo, l.organo_contratacion AS organo, l.cpv, l.ccaa,
               l.tipo_contrato, l.fuente, l.importe
        FROM licitaciones l
        WHERE l.importe > 0
          AND COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed'
          AND COALESCE(l.estado, '') NOT IN ({cerrados})
          AND NOT EXISTS (SELECT 1 FROM adjudicaciones a WHERE a.licitacion_id = l.id_externo)
          AND {exclude_duplicados_sql()}
        ORDER BY l.fecha_publicacion DESC
        LIMIT %s
    """  # noqa: S608 — fragmento constante de services.dedupe; valores con ?
    with connect_read() as c:
        abiertas = rows_to_dicts(
            c.execute(sql, (*ESTADOS_CERRADOS, max(1, min(int(limit), 50_000))))
        )

    filas: list[FilaDataset] = []
    for row in abiertas:
        features = _features_estaticas(row, fecha_score)
        features.update(
            acum.features_historicas(
                organo=row.get("organo"),
                cpv4=_cpv4(row.get("cpv")),
                ccaa=row.get("ccaa"),
                fecha=fecha_score,
            )
        )
        filas.append(
            FilaDataset(
                licitacion_id=str(row["id_externo"]),
                fecha=fecha_score.strftime("%Y-%m-%d"),
                features=features,
            )
        )
    return filas
