"""Paridad del scoring por columnas con el bucle por filas al que sustituye.

Hasta 2026-09 ``services/analytics/scoring.py`` puntuaba fila a fila
(``iterrows`` + ``_score_row`` + un ``ScoredOpportunity`` con su explicación
por cada candidata) y la afinidad hacía su propio ``iterrows``. El motor por
columnas (``_puntuar``) tiene que dar **exactamente** lo mismo: mismos scores,
mismo orden y desempate, mismas banderas y explicaciones y el mismo double en
cada celda del desglose —un ``-0.0`` donde había ``0.0`` ya cambia el JSON—.

Por eso el código de antes vive aquí, copiado del commit ``d759d42c`` sin los
logs, como oráculo: ``_score_row_por_filas``, ``_get_scoring_por_filas``,
``_score_dataframe_por_filas`` y ``_score_affinity_batch_por_filas``. No se
refactoriza ni se «arregla»: su única función es decir qué respondía el
sistema antes del cambio.

Las tres piezas en las que numpy no se comporta como Python —``round(x, 2)``,
la ``sum`` compensada y ``min``/``max`` con NaN— se prueban además contra
Python valor a valor, con los casos frontera construidos a mano.
"""

from __future__ import annotations

import dataclasses
import math
import random
import sys
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import Any
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

import services.analytics.scoring as sc_mod
from services.analytics import affinity as af_mod
from services.analytics.affinity import AffinityBatch, AffinityPortfolio, build_portfolio
from services.analytics.scoring import (
    ANULACION_UMBRAL,
    FLAG_ANULACION,
    FilaPuntuada,
    ScoredOpportunity,
    ScoringFilters,
    ScoringProfile,
    ScoringResult,
    ScoringSignalsHealth,
    _band,
    _cpv4,
    _ScoringContext,
    tasa_anulacion,
)
from services.analytics.scoring_explicacion import HechosDeFila, explicar
from services.analytics.scoring_signals import (
    ORIGEN_DESCONOCIDO,
    SIGNAL_ERROR,
    CompetenciaStats,
    ImportePercentiles,
    MargenStats,
)

# Las fechas sintéticas mezclan formatos a propósito (offsets distintos, basura)
# y pandas avisa de que las parsea una a una. Es el mismo `to_datetime` para el
# motor y para el oráculo; el aviso no dice nada de lo que se prueba aquí.
pytestmark = pytest.mark.filterwarnings("ignore:Could not infer format:UserWarning")

# ---------------------------------------------------------------------------
# Oráculo: el scoring por filas tal como estaba antes del cambio
# ---------------------------------------------------------------------------


def _score_row_por_filas(
    row: pd.Series,
    ctx: _ScoringContext,
    *,
    con_explicacion: bool = True,
) -> FilaPuntuada:
    flags: list[str] = []
    desglose: dict[str, float] = {}
    fraccion: dict[str, float | None] = {}
    w = ctx.weights

    importe = row.get("importe")
    if pd.notna(importe) and ctx.imp_p90 > ctx.imp_p10:
        ratio = max(0.0, min(1.0, (float(importe) - ctx.imp_p10) / (ctx.imp_p90 - ctx.imp_p10)))
        d_importe = ratio * w.get("importe", 0)
        fraccion["importe"] = ratio
    elif pd.notna(importe):
        d_importe = w.get("importe", 0) * 0.5
        fraccion["importe"] = None
    else:
        d_importe = w.get("importe", 0) * 0.5
        flags.append("sin_importe")
        fraccion["importe"] = None
    desglose["importe"] = round(d_importe, 2)

    titulo = str(row.get("titulo", "") or "")
    titulo_lower = titulo.casefold()

    d_plazo = 0.0
    fecha_limite = row.get("fecha_limite_dt") if "fecha_limite_dt" in row.index else None
    if pd.notna(fecha_limite) and fecha_limite is not None:
        days_left = (fecha_limite - ctx.now).days
        escalon = 0.0
        if 7 <= days_left <= 90:
            escalon = 1.0
        elif 0 <= days_left < 7:
            escalon = 0.5
        elif 90 < days_left <= 180:
            escalon = 0.7
        elif days_left > 180:
            escalon = 0.3
        d_plazo = float(w.get("plazo", 0)) * escalon
        fraccion["plazo"] = escalon
    else:
        d_plazo = w.get("plazo", 0) * 0.5
        flags.append("sin_plazo")
        fraccion["plazo"] = None
    desglose["plazo"] = round(d_plazo, 2)

    cpv4 = _cpv4(row.get("cpv"))
    media_ofertas: float | None = None
    if cpv4 is not None:
        media_ofertas = ctx.competencia_stats.media_por_cpv4.get(cpv4)
    if media_ofertas is None:
        media_ofertas = ctx.competencia_stats.media_global

    if media_ofertas is not None:
        f_competencia = 1.0 - max(0.0, min(1.0, (media_ofertas - 1.0) / 9.0))
        d_competencia = f_competencia * w.get("competencia", 0)
        fraccion["competencia"] = f_competencia
    else:
        d_competencia = w.get("competencia", 0) * 0.5
        flags.append("sin_historico_competencia")
        fraccion["competencia"] = None
    desglose["competencia"] = round(d_competencia, 2)

    id_externo = str(row.get("id_externo", ""))
    baja: float | None = ctx.margen_stats.p50_por_licitacion.get(id_externo)
    if baja is None and cpv4 is not None:
        baja = ctx.margen_stats.baja_media_por_cpv4.get(cpv4)
    if baja is None:
        baja = ctx.margen_stats.baja_media_global

    if baja is not None:
        fraccion_margen = 1.0 - min(baja / 0.40, 1.0)
        d_margen = fraccion_margen * w.get("margen", 0)
        fraccion["margen"] = fraccion_margen
    else:
        d_margen = w.get("margen", 0) * 0.5
        flags.append("sin_prediccion")
        fraccion["margen"] = None
    desglose["margen"] = round(d_margen, 2)

    if ctx.affinity_scores and "afinidad" in w:
        fraccion_af = ctx.affinity_scores.get(id_externo, 0.0)
        d_afinidad = fraccion_af * w["afinidad"]
        desglose["afinidad"] = round(d_afinidad, 2)
        fraccion["afinidad"] = fraccion_af

    if w.get("senal_tecnica", 0) > 0:
        if ctx.tech_signal is None:
            d_tecnica = w["senal_tecnica"] * 0.5
            fraccion["senal_tecnica"] = None
        else:
            fuerza = ctx.tech_signal.get(id_externo)
            if fuerza is None:
                d_tecnica = w["senal_tecnica"] * 0.5
                flags.append("sin_senal_tecnica")
                fraccion["senal_tecnica"] = None
            else:
                f_tecnica = max(0.0, min(1.0, float(fuerza)))
                d_tecnica = f_tecnica * w["senal_tecnica"]
                fraccion["senal_tecnica"] = f_tecnica
        desglose["senal_tecnica"] = round(d_tecnica, 2)

    d_riesgo = 0.0
    if "sin_importe" in flags:
        d_riesgo -= 5.0
    if not titulo_lower.strip():
        d_riesgo -= 3.0
        flags.append("sin_titulo")
    if "sin_plazo" in flags:
        d_riesgo -= 2.0

    importe_val = row.get("importe")
    if pd.notna(importe_val) and (ctx.importe_min is not None or ctx.importe_max is not None):
        imp_float = float(importe_val)
        fuera_de_rango = (ctx.importe_min is not None and imp_float < ctx.importe_min) or (
            ctx.importe_max is not None and imp_float > ctx.importe_max
        )
        if fuera_de_rango:
            d_riesgo -= 15.0
            flags.append("fuera_de_rango")

    if ctx.penalizacion_anulacion > 0 and ctx.tasas_anulacion:
        medida = tasa_anulacion(row.get("organo_contratacion"), row.get("cpv"), ctx.tasas_anulacion)
        if medida is not None and medida[0] >= ANULACION_UMBRAL:
            d_riesgo -= float(ctx.penalizacion_anulacion)
            flags.append(FLAG_ANULACION)

    desglose["riesgo"] = round(d_riesgo, 2)

    dim_sum = sum(v for k, v in desglose.items() if k != "riesgo")
    total = dim_sum + d_riesgo
    final = max(0, min(round(total), 100))

    explicacion = (
        explicar(
            HechosDeFila(
                score=final,
                fraccion=fraccion,
                media_ofertas=media_ofertas,
                baja_esperada=baja,
                margen_origen=ctx.margen_stats.origen,
                afinidad_metodo=ctx.affinity_method,
                risk_flags=tuple(flags),
            )
        )
        if con_explicacion
        else []
    )
    return FilaPuntuada(final, _band(final), flags, desglose, explicacion)


def _score_dataframe_por_filas(
    base_df: pd.DataFrame,
    target_df: pd.DataFrame,
    *,
    importe_percentiles: ImportePercentiles | None = None,
    tecnologia: str | None = None,
) -> pd.DataFrame:
    if target_df.empty:
        return pd.DataFrame(columns=["id_externo", "score", "band"])

    ctx = sc_mod._build_context(
        base_df, importe_percentiles=importe_percentiles, tecnologia=tecnologia
    )

    ids: list[str] = []
    scores: list[int] = []
    bands: list[str] = []
    for _, row in target_df.iterrows():
        s, band, _flags, _desglose, _explicacion = _score_row_por_filas(
            row, ctx, con_explicacion=False
        )
        ids.append(str(row.get("id_externo", "")))
        scores.append(s)
        bands.append(band)

    return pd.DataFrame({"id_externo": ids, "score": scores, "band": bands})


def _get_scoring_por_filas(
    filters: ScoringFilters,
    user_key: str | None = None,
    organization_id: int | None = None,
    *,
    user_id: int | None = None,
) -> ScoringResult:
    if filters.ids:
        rows = sc_mod._repo.licitaciones_by_ids([str(i) for i in filters.ids])
    else:
        rows = sc_mod._repo.scoring_candidates(
            hoy_iso=pd.Timestamp.now("UTC").strftime("%Y-%m-%d"),
            filters=sc_mod._ambito_como_filtros(organization_id, filters.tecnologia),
        )

    if not rows:
        return ScoringResult()

    df = pd.DataFrame(rows)
    df = df.assign(
        importe=pd.to_numeric(df["importe"], errors="coerce"),
        fecha_limite_dt=pd.to_datetime(df["fecha_limite"], errors="coerce", utc=True),
    )

    if filters.exclude_dismissed and user_key is not None and not filters.ids:
        try:
            from db import radar_dismissals

            descartadas = set(radar_dismissals.list_ids(user_key, user_id=user_id))
        except Exception:
            descartadas = set()
        if descartadas:
            df = df[~df["id_externo"].astype(str).isin(descartadas)]
            if df.empty:
                return ScoringResult()

    profile: ScoringProfile | None = None
    profile_status = "ok"
    if user_key is not None:
        try:
            from db.repositories.user_profiles import (
                get_own_user_profile,
                get_user_profile,
            )

            raw_profile = (
                get_user_profile(user_key, organization_id, user_id=user_id)
                if organization_id is not None
                else get_own_user_profile(user_key, user_id=user_id)
            )
            if raw_profile is not None:
                profile = ScoringProfile(
                    weights=raw_profile.get("weights"),
                    afinidad_keywords=raw_profile.get("afinidad_keywords"),
                    cpvs=raw_profile.get("cpvs"),
                    importe_min=raw_profile.get("importe_min"),
                    importe_max=raw_profile.get("importe_max"),
                )
        except Exception:
            profile_status = "error"

    ctx = sc_mod._build_context(
        df,
        profile=profile,
        importe_percentiles=sc_mod.load_importe_percentiles(),
        tecnologia=filters.tecnologia,
        organization_id=organization_id,
    )

    id_filter = {str(i) for i in filters.ids} if filters.ids else None
    work = df

    scored: list[ScoredOpportunity] = []
    for _, row in work.iterrows():
        s, band, flags, desglose, explicacion = _score_row_por_filas(row, ctx)
        if id_filter is None:
            if s < filters.min_score:
                continue
            if filters.band and band != filters.band:
                continue
        scored.append(
            ScoredOpportunity(
                id_externo=str(row.get("id_externo", "")),
                titulo=row.get("titulo") if pd.notna(row.get("titulo")) else None,
                organo_contratacion=row.get("organo_contratacion")
                if pd.notna(row.get("organo_contratacion"))
                else None,
                importe=float(row["importe"]) if pd.notna(row.get("importe")) else None,
                fecha_limite=str(row["fecha_limite"])
                if pd.notna(row.get("fecha_limite"))
                else None,
                tecnologia=str(row["tecnologia"]) if pd.notna(row.get("tecnologia")) else None,
                fecha_publicacion=str(row["fecha_publicacion"])
                if pd.notna(row.get("fecha_publicacion"))
                else None,
                cpv=str(row["cpv"]) if pd.notna(row.get("cpv")) else None,
                ccaa=str(row["ccaa"]) if pd.notna(row.get("ccaa")) else None,
                ml_tech_principal=str(row["ml_tech_principal"])
                if pd.notna(row.get("ml_tech_principal"))
                else None,
                url=str(row["url"]) if pd.notna(row.get("url")) else None,
                fuente=str(row["fuente"]) if pd.notna(row.get("fuente")) else None,
                estado=str(row["estado"]) if pd.notna(row.get("estado")) else None,
                procedimiento=str(row["procedimiento"])
                if pd.notna(row.get("procedimiento"))
                else None,
                tramitacion=str(row["tramitacion"]) if pd.notna(row.get("tramitacion")) else None,
                score=s,
                band=band,
                risk_flags=flags,
                desglose=desglose,
                explicacion=explicacion,
            )
        )

    total = len(scored)
    if id_filter is None:
        scored.sort(key=lambda x: x.score, reverse=True)
        scored = scored[: filters.limit]

    return ScoringResult(
        opportunities=scored,
        total_scored=total,
        signals=ScoringSignalsHealth(
            competencia=ctx.competencia_stats.status,
            margen=ctx.margen_stats.status,
            margen_origen=(
                ctx.margen_stats.origen
                if ctx.margen_stats.status != SIGNAL_ERROR
                else ORIGEN_DESCONOCIDO
            ),
            percentiles_fuente=ctx.percentiles_fuente,
            afinidad_metodo=ctx.affinity_method,
            afinidad_origen=ctx.affinity_origen,
            senal_tecnica="error" if ctx.tech_signal is None else "ok",
            perfil=profile_status,
            anulacion_organo=(
                "apagada"
                if ctx.penalizacion_anulacion <= 0
                else "error"
                if ctx.tasas_anulacion is None
                else "ok"
            ),
        ),
    )


def _candidate_text_por_filas(row: pd.Series) -> str:
    parts = [
        str(row.get("titulo") or "").strip(),
        str(row.get("descripcion") or "").strip(),
        str(row.get("cpv") or "").strip(),
    ]
    return " · ".join(part for part in parts if part)


def _fallback_score_por_filas(row: pd.Series, portfolio: AffinityPortfolio, pattern: Any) -> float:
    hits = 0
    if pattern is not None:
        texto = " ".join(
            part
            for part in (str(row.get("titulo") or ""), str(row.get("descripcion") or ""))
            if part
        )
        hits = len({match.group(0).casefold() for match in pattern.finditer(texto)})
    keyword_score = min(hits / 3.0, 1.0)
    return max(keyword_score, af_mod._cpv_similarity(row.get("cpv"), portfolio.cpvs))


def _score_affinity_batch_por_filas(
    df: pd.DataFrame, portfolio: AffinityPortfolio
) -> AffinityBatch:
    if df.empty or not portfolio.available:
        return AffinityBatch()

    ids = [str(value) for value in df.get("id_externo", pd.Series(dtype=str)).tolist()]
    rows = [row for _, row in df.iterrows()]
    pattern = af_mod._keyword_pattern(portfolio.keywords)
    fallback = {
        row_id: round(_fallback_score_por_filas(row, portfolio, pattern), 6)
        for row_id, row in zip(ids, rows, strict=True)
    }

    try:
        from services.embeddings import embeddings_available, encode_texts

        if not embeddings_available():
            return AffinityBatch(scores=fallback, method="keyword_cpv_fallback")

        portfolio_items = [
            *portfolio.keywords,
            *(f"CPV {cpv}" for cpv in portfolio.cpvs),
            *portfolio.contracts,
        ]
        candidates = [_candidate_text_por_filas(row) for row in rows]
        vectors = encode_texts([*portfolio_items, *candidates])
        split = len(portfolio_items)
        portfolio_vectors = np.asarray(vectors[:split], dtype=float)
        candidate_vectors = np.asarray(vectors[split:], dtype=float)
        if (
            portfolio_vectors.ndim != 2
            or candidate_vectors.ndim != 2
            or len(candidate_vectors) != len(rows)
        ):
            raise ValueError("shape de embeddings inesperada")

        similarities = candidate_vectors @ portfolio_vectors.T
        semantic_scores = similarities.max(axis=1)
        scores = {
            row_id: round(
                max(
                    0.0,
                    min(1.0, float(semantic)),
                    af_mod._cpv_similarity(row.get("cpv"), portfolio.cpvs),
                ),
                6,
            )
            for row_id, row, semantic in zip(ids, rows, semantic_scores, strict=True)
        }
        return AffinityBatch(scores=scores, method="semantic_embeddings")
    except Exception:
        return AffinityBatch(scores=fallback, method="keyword_cpv_fallback")


# ---------------------------------------------------------------------------
# Datos sintéticos: cada rama que el scoring distingue, y empates a propósito
# ---------------------------------------------------------------------------

_AHORA = pd.Timestamp("2026-09-24T10:30:00Z")

#: Fechas límite respecto a `_AHORA`: cada escalón del plazo (0, 7, 90, 180
#: días) con sus bordes a un segundo, y vencidas por horas —`Timedelta.days`
#: redondea hacia abajo, así que una hora vencida son -1 días—.
_DESPLAZAMIENTOS = [
    pd.Timedelta(days=-400),
    pd.Timedelta(days=-1),
    pd.Timedelta(hours=-1),
    pd.Timedelta(seconds=-1),
    pd.Timedelta(0),
    pd.Timedelta(hours=1),
    pd.Timedelta(days=6, hours=23, minutes=59, seconds=59),
    pd.Timedelta(days=7),
    pd.Timedelta(days=7, seconds=-1),
    pd.Timedelta(days=30, hours=5),
    pd.Timedelta(days=90),
    pd.Timedelta(days=90, hours=23),
    pd.Timedelta(days=91),
    pd.Timedelta(days=180),
    pd.Timedelta(days=180, hours=23, minutes=59),
    pd.Timedelta(days=181),
    pd.Timedelta(days=400),
]

_TITULOS = [
    "Mantenimiento del sistema de gestión económica",
    "Consultoría y soporte técnico de aplicaciones ERP",
    "Migración ERP y soporte SAP",
    "Suministro de mobiliario escolar",
    "SOPORTE soporte Soporte",
    "",
    "   ",
    None,
]
_DESCRIPCIONES = ["Incluye soporte de los módulos ERP", "Sin descripción", "", None]
#: CPV con uno o varios códigos, con y sin dígito de control, cortos, no
#: numéricos y numéricos sin comillas (así llegan algunos ficheros).
_CPVS: list[Any] = [
    "72000000",
    "72260000-5",
    "48000000;72000000",
    "72000000,48000000",
    " 4800 ",
    "7226",
    "722",
    "abcd1234",
    "",
    None,
    33000000,
    45000000.0,
    "99990000",  # su CPV-4 tiene una media NaN en `_stats`
]
_ORGANOS: list[Any] = [
    "Organo 3",
    "ORGANO 3",
    "Organo 5",
    "Organo 7",
    "  Ayuntamiento de Anulaciones  ",
    "Organo sin historia",
    "",
    None,
]
_IMPORTES: list[Any] = [
    None,
    0.0,
    -1_000.0,
    1_000.0,
    5_000.0,
    25_000.5,
    80_000.0,
    150_000.0,
    400_000.0,
    2e9,
    12_345,
    "33000.25",
    -0.0,
]
_TASAS: dict[tuple[str, str], tuple[int, int]] = {
    ("organo 3", "*"): (20, 8),  # 40 %: penaliza
    ("organo 5", "7200"): (12, 6),  # 50 % en su CPV-4
    ("organo 5", "*"): (40, 2),  # 5 % en el órgano entero
    ("organo 7", "*"): (9, 9),  # por debajo de la muestra mínima
    ("ayuntamiento de anulaciones", "*"): (40, 10),  # 25 %: justo el umbral
}


def _fecha(rng: random.Random) -> Any:
    opcion = rng.random()
    if opcion < 0.08:
        return None
    if opcion < 0.1:
        return "no-es-una-fecha"
    marca = _AHORA + rng.choice(_DESPLAZAMIENTOS)
    if opcion < 0.2:
        return marca.tz_convert("Europe/Madrid").isoformat()
    return marca.isoformat()


def _filas(n: int, semilla: int) -> list[dict[str, Any]]:
    """Filas como las devuelve `scoring_candidates`, con todas las ramas.

    Una de cada seis es copia de la anterior con otro id, para que haya
    empates de score y el desempate por orden de llegada tenga algo que
    decidir. Otra de cada once omite claves, que es como aparecen los NaN de
    objeto que el bucle por filas trataba de forma peculiar (``str(nan)``).
    """
    rng = random.Random(semilla)
    filas: list[dict[str, Any]] = []
    for i in range(n):
        if filas and i % 6 == 0:
            fila = dict(filas[-1])
        else:
            fila = {
                "titulo": rng.choice(_TITULOS),
                "descripcion": rng.choice(_DESCRIPCIONES),
                "organo_contratacion": rng.choice(_ORGANOS),
                "importe": rng.choice(_IMPORTES)
                if rng.random() < 0.7
                else round(rng.uniform(0, 600_000), rng.choice([0, 2, 5])),
                "cpv": rng.choice(_CPVS),
                "fecha_limite": _fecha(rng),
                "estado": rng.choice(["PUB", "ADM", "EV", None]),
                "ccaa": rng.choice(["Madrid", "Galicia", None]),
                "tecnologia": rng.choice(["SAP", "MICROSOFT", None]),
                "fecha_publicacion": rng.choice(["2026-09-01T00:00:00+00:00", None]),
                "ml_tech_principal": rng.choice(["SAP", None]),
                "url": rng.choice([f"https://example.org/{i}", None]),
                "fuente": rng.choice(["placsp", "ted", "pscp", None]),
                "procedimiento": rng.choice(["1", "2", None]),
                "tramitacion": rng.choice(["1", None]),
            }
        fila["id_externo"] = f"S{semilla}-{i:04d}"
        if i % 11 == 5:
            for clave in ("titulo", "organo_contratacion", "ccaa"):
                fila.pop(clave, None)
        filas.append(fila)
    return filas


def _df(filas: list[dict[str, Any]]) -> pd.DataFrame:
    """El DataFrame tal como lo arma `get_scoring` a partir de las filas."""
    df = pd.DataFrame(filas)
    return df.assign(
        importe=pd.to_numeric(df["importe"], errors="coerce"),
        fecha_limite_dt=pd.to_datetime(df["fecha_limite"], errors="coerce", utc=True),
    )


def _df_objetos(df: pd.DataFrame) -> pd.DataFrame:
    """El mismo lote con todas las columnas `object`: el camino fila a fila del motor."""
    return df.astype(object).where(df.notna(), None)


def _stats(ids: list[str], semilla: int) -> tuple[CompetenciaStats, MargenStats]:
    rng = random.Random(semilla)
    comp = CompetenciaStats(
        # Una media NaN: `min`/`max` de Python la llevan a 1.0, `np.clip` no.
        media_por_cpv4={
            "7200": 2.5,
            "7226": 6.0,
            "4800": 9.5,
            "3300": 1.0,
            "4500": 12.0,
            "9999": math.nan,
        },
        media_global=4.2,
        status="ok",
    )
    p50 = {
        id_: rng.choice([0.0, 0.05, 0.1, 0.125, 0.3, 0.4, 0.55, -0.05, rng.random() * 0.6])
        for id_ in ids
        if rng.random() < 0.4
    }
    marg = MargenStats(
        p50_por_licitacion=p50,
        baja_media_por_cpv4={"7200": 0.12, "4800": 0.45, "7226": 0.2},
        baja_media_global=0.18,
        status="ok",
        n_modelo=3,
        n_baseline=4,
    )
    return comp, marg


def _contextos(df: pd.DataFrame, semilla: int) -> dict[str, _ScoringContext]:
    """Cuatro contextos que juntos recorren cada rama de cada dimensión."""
    rng = random.Random(semilla)
    ids = [str(v) for v in df["id_externo"].tolist()]
    comp, marg = _stats(ids, semilla)
    afinidad = {
        id_: rng.choice([0.0, 0.3, 0.3000001, 0.55, 0.549999, 1.0, round(rng.random(), 6)])
        for id_ in ids
        if rng.random() < 0.8
    }
    # Fracciones cuyo producto por el peso 15 cae a medio céntimo: ahí
    # `np.round` y `round` redondean distinto.
    afinidad.update(zip(ids, [0.035, 0.049, 0.063, 0.105, 0.147], strict=False))
    tecnica = {
        id_: rng.choice([0.0, 0.3, 0.55, 0.9, 1.2, -0.1, rng.random()])
        for id_ in ids
        if rng.random() < 0.6
    }
    tecnica[ids[7]] = math.nan
    completo = _ScoringContext(
        imp_p10=5_000.0,
        imp_p90=400_000.0,
        weights={
            "importe": 20,
            "plazo": 15,
            "competencia": 20,
            "margen": 20,
            "afinidad": 15,
            "senal_tecnica": 10,
        },
        keywords=["erp", "soporte"],
        affinity_scores=afinidad,
        affinity_method="keyword_cpv_fallback",
        competencia_stats=comp,
        margen_stats=marg,
        percentiles_fuente="universo_vivo",
        tech_signal=tecnica,
        importe_min=10_000.0,
        importe_max=1_000_000.0,
        now=_AHORA,
        penalizacion_anulacion=8,
        tasas_anulacion=_TASAS,
    )
    sin_senales = _ScoringContext(
        imp_p10=50_000.0,
        imp_p90=50_000.0,
        weights=sc_mod._effective_weights(
            {"importe": 25, "plazo": 15, "competencia": 25, "margen": 20, "afinidad": 15}, []
        ),
        keywords=[],
        affinity_scores={},
        affinity_method="unavailable",
        competencia_stats=CompetenciaStats(status="vacia"),
        margen_stats=MargenStats(status="error"),
        percentiles_fuente="sin_datos",
        tech_signal=None,
        now=_AHORA,
        penalizacion_anulacion=0,
        tasas_anulacion={},
    )
    legado = _ScoringContext(
        imp_p10=1_000.0,
        imp_p90=90_000.0,
        weights={"importe": 25, "plazo": 25, "competencia": 25, "margen": 25},
        keywords=[],
        affinity_scores=afinidad,
        affinity_method="keyword_cpv_fallback",
        competencia_stats=CompetenciaStats(media_por_cpv4={"7200": 3.0}, status="ok"),
        margen_stats=MargenStats(baja_media_por_cpv4={"7200": 0.3}, status="ok"),
        percentiles_fuente="global",
        tech_signal={},
        importe_min=25_000.5,
        now=_AHORA,
        penalizacion_anulacion=20,
        tasas_anulacion=None,
    )
    # Con P10 = 0, un importe -0.0 da un ratio -0.0 que `max(0.0, …)` deja en 0.0.
    semantico = dataclasses.replace(
        completo,
        imp_p10=0.0,
        imp_p90=250_000.0,
        weights={
            "importe": 19,
            "plazo": 17,
            "competencia": 21,
            "margen": 13,
            "afinidad": 17,
            "senal_tecnica": 13,
        },
        affinity_method="semantic_embeddings",
        margen_stats=dataclasses.replace(marg, n_baseline=0),
        tech_signal={},
        importe_min=None,
        importe_max=150_000.0,
        penalizacion_anulacion=30,
    )
    return {
        "completo": completo,
        "sin_senales": sin_senales,
        "legado": legado,
        "semantico": semantico,
    }


def _bits(fila: FilaPuntuada) -> tuple[Any, ...]:
    """La fila con cada float por su representación exacta (signo del cero incluido)."""
    return (
        fila.score,
        fila.band,
        fila.flags,
        [(clave, float(valor).hex()) for clave, valor in fila.desglose.items()],
        fila.explicacion,
    )


# ---------------------------------------------------------------------------
# El motor, fila a fila, contra el oráculo
# ---------------------------------------------------------------------------

_LOTE = _filas(360, semilla=7)


@pytest.mark.parametrize("contexto", ["completo", "sin_senales", "legado", "semantico"])
@pytest.mark.parametrize("tipos", ["columnas_tipadas", "columnas_objeto"])
def test_cada_fila_del_lote_es_identica_a_la_del_bucle_por_filas(contexto: str, tipos: str):
    df = _df(_LOTE)
    if tipos == "columnas_objeto":
        df = _df_objetos(df)
    ctx = _contextos(df, semilla=11)[contexto]

    puntuaciones = sc_mod._puntuar(df, ctx)

    assert len(puntuaciones.ids) == len(df)
    for posicion, (_, row) in enumerate(df.iterrows()):
        esperado = _score_row_por_filas(row, ctx)
        assert _bits(puntuaciones.fila(posicion)) == _bits(esperado), (contexto, posicion)
        assert puntuaciones.fila(posicion, con_explicacion=False).explicacion == []


@pytest.mark.parametrize("contexto", ["completo", "legado"])
def test_score_row_sigue_siendo_el_de_antes(contexto: str):
    """`_score_row` (la API que usan los tests de la fórmula) delega en el motor."""
    df = _df_objetos(_df(_LOTE[:120]))
    ctx = _contextos(df, semilla=3)[contexto]
    for _, row in df.iterrows():
        assert _bits(sc_mod._score_row(row, ctx)) == _bits(_score_row_por_filas(row, ctx))


def test_una_fila_sin_ninguna_columna_opcional():
    """Sin `titulo`, `cpv`, fecha ni órgano: `row.get` daba vacío y el motor también."""
    df = pd.DataFrame([{"id_externo": "SOLO", "importe": 1_000.0}])
    ctx = _contextos(_df(_LOTE[:10]), semilla=1)["completo"]
    esperado = _score_row_por_filas(df.iloc[0], ctx)
    assert _bits(sc_mod._puntuar(df, ctx).fila(0)) == _bits(esperado)
    assert set(esperado.flags) >= {"sin_plazo", "sin_titulo"}


def test_la_suma_de_dimensiones_es_la_de_python_tambien_en_el_score():
    """Filas en las que una suma ingenua de las dimensiones cambia el entero.

    Encontradas por búsqueda (78 de 60 000 filas aleatorias): la suma
    redondeada cae en ``x,5`` y un ulp de diferencia entre sumar en orden y la
    ``sum`` compensada de Python decide hacia dónde redondea ``round``. En un
    Radar de 1,6 k candidatas serían un par de scores distintos por petición.
    """
    ahora = _AHORA
    casos = [
        ("N1873", 203209.21, 0.0217, 0.479711, 0.0682),
        ("N2212", 47647.51, 0.0607, 0.950131, 0.4462),
        ("N3543", 397091.64, 0.3758, 0.070619, 0.4715),
        ("N6144", 218424.74, 0.3292, 0.768257, 0.0964),
    ]
    df = pd.DataFrame(
        {
            "id_externo": [c[0] for c in casos],
            "titulo": "Soporte",
            "importe": [c[1] for c in casos],
            "cpv": "72000000",
            "fecha_limite_dt": ahora + pd.Timedelta(days=30),
        }
    )
    ctx = _ScoringContext(
        imp_p10=5_000.0,
        imp_p90=400_000.0,
        weights={
            "importe": 20,
            "plazo": 15,
            "competencia": 20,
            "margen": 20,
            "afinidad": 15,
            "senal_tecnica": 10,
        },
        keywords=["soporte"],
        affinity_scores={c[0]: c[3] for c in casos},
        affinity_method="keyword_cpv_fallback",
        competencia_stats=CompetenciaStats(media_por_cpv4={"7200": 2.5}, status="ok"),
        margen_stats=MargenStats(p50_por_licitacion={c[0]: c[2] for c in casos}, status="ok"),
        percentiles_fuente="universo_vivo",
        tech_signal={c[0]: c[4] for c in casos},
        now=ahora,
    )

    puntuaciones = sc_mod._puntuar(df, ctx)
    for posicion, (_, row) in enumerate(df.iterrows()):
        esperado = _score_row_por_filas(row, ctx)
        assert _bits(puntuaciones.fila(posicion)) == _bits(esperado)
        dimensiones = [v for k, v in esperado.desglose.items() if k != "riesgo"]
        ingenua = dimensiones[0]
        for valor in dimensiones[1:]:
            ingenua += valor
        # Guardia del caso: con la suma ingenua el score sería otro.
        assert max(0, min(round(ingenua + esperado.desglose["riesgo"]), 100)) != esperado.score


def test_un_p50_nan_revienta_igual_que_antes():
    """Una NaN en una dimensión no tiene entero: antes `round` lanzaba y ahora también.

    Devolver un entero basura en silencio sería peor que el error de siempre.
    """
    df = _df(_LOTE[:20])
    base = _contextos(df, semilla=5)["completo"]
    ctx = dataclasses.replace(
        base,
        margen_stats=MargenStats(p50_por_licitacion={str(df["id_externo"].iloc[4]): math.nan}),
    )
    with pytest.raises(ValueError) as antes:
        for _, row in df.iterrows():
            _score_row_por_filas(row, ctx)
    with pytest.raises(ValueError) as ahora:
        sc_mod._puntuar(df, ctx)
    assert str(ahora.value) == str(antes.value)


# ---------------------------------------------------------------------------
# get_scoring y score_dataframe completos contra el oráculo
# ---------------------------------------------------------------------------


@contextmanager
def _entorno(
    filas: list[dict[str, Any]],
    *,
    perfil: dict[str, Any] | None,
    tecnica: dict[str, float] | None,
    tasas: dict[tuple[str, str], tuple[int, int]] | None,
    descartes: list[str] | None = None,
    semilla: int = 0,
) -> Iterator[None]:
    """Mismo acceso a datos, mockeado, para la versión nueva y el oráculo."""
    ids = [str(f["id_externo"]) for f in filas]
    comp, marg = _stats(ids, semilla)

    def _por_ids(pedidos: list[str]) -> list[dict[str, Any]]:
        quiero = {str(i) for i in pedidos}
        return [f for f in filas if str(f["id_externo"]) in quiero]

    def _tecnica(*_a: Any, **_k: Any) -> dict[str, float]:
        if tecnica is None:
            raise RuntimeError("consulta caída")
        return dict(tecnica)

    def _tasas(*_a: Any, **_k: Any) -> dict[tuple[str, str], tuple[int, int]]:
        if tasas is None:
            raise RuntimeError("consulta caída")
        return dict(tasas)

    with ExitStack() as stack:
        stack.enter_context(patch.object(sc_mod._repo, "scoring_candidates", return_value=filas))
        stack.enter_context(patch.object(sc_mod._repo, "licitaciones_by_ids", side_effect=_por_ids))
        stack.enter_context(patch.object(sc_mod._repo, "tech_signal_by_ids", side_effect=_tecnica))
        stack.enter_context(
            patch.object(
                sc_mod,
                "load_importe_percentiles",
                return_value=ImportePercentiles(p10=5_000.0, p90=400_000.0, fuente="universo_vivo"),
            )
        )
        stack.enter_context(patch.object(sc_mod, "load_competencia_stats", return_value=comp))
        stack.enter_context(patch.object(sc_mod, "load_margen_stats", return_value=marg))
        stack.enter_context(
            patch("db.repositories.tasas_anulacion.tasas_por_organos", side_effect=_tasas)
        )
        stack.enter_context(
            patch("db.repositories.user_profiles.get_user_profile", return_value=perfil)
        )
        stack.enter_context(
            patch("db.repositories.user_profiles.get_own_user_profile", return_value=perfil)
        )
        stack.enter_context(
            patch.object(af_mod, "build_organization_portfolio", return_value=AffinityPortfolio())
        )
        stack.enter_context(patch("services.embeddings.embeddings_available", return_value=False))
        stack.enter_context(
            patch.object(sc_mod, "_ambito_como_filtros", return_value=sc_mod.LicitacionesFilters())
        )
        stack.enter_context(patch("db.radar_dismissals.list_ids", return_value=descartes or []))
        yield


def _oraculo(filters: ScoringFilters, **kwargs: Any) -> ScoringResult:
    """El `get_scoring` de antes, con la afinidad de antes."""
    with patch.object(sc_mod, "score_affinity_batch", _score_affinity_batch_por_filas):
        return _get_scoring_por_filas(filters, **kwargs)


_PERFIL = {
    "weights": {
        "importe": 20,
        "plazo": 15,
        "competencia": 20,
        "margen": 20,
        "afinidad": 15,
        "senal_tecnica": 10,
        FLAG_ANULACION: 8,
    },
    "afinidad_keywords": ["erp", "soporte", "mantenimiento"],
    "cpvs": ["72260000"],
    "importe_min": 5_000.0,
    "importe_max": 1_000_000.0,
}


def _filas_lejos_de_medianoche(n: int, semilla: int) -> list[dict[str, Any]]:
    """Filas con la fecha límite a medio día del corte de cada escalón.

    `get_scoring` construye su contexto con la hora real, y el oráculo corre
    unos milisegundos después: sin este margen, una fecha a un segundo de un
    escalón podría caer en días distintos en cada llamada. Los bordes exactos
    los cubren los tests de arriba, con la hora fijada.
    """
    ahora = pd.Timestamp.now("UTC")
    rng = random.Random(semilla)
    filas = _filas(n, semilla)
    for fila in filas:
        if fila.get("fecha_limite") not in (None, "no-es-una-fecha"):
            dias = rng.choice([-10, -1, 0, 3, 6, 7, 45, 90, 91, 150, 180, 181, 500])
            fila["fecha_limite"] = (ahora + pd.Timedelta(days=dias, hours=12)).isoformat()
    return filas


_FILTROS = [
    ScoringFilters(),
    ScoringFilters(limit=5),
    ScoringFilters(limit=24, min_score=30),
    ScoringFilters(limit=500),
    ScoringFilters(limit=0),
    ScoringFilters(limit=-3),
    ScoringFilters(band="Tibia"),
    ScoringFilters(band="Atractiva", min_score=55, limit=7),
    ScoringFilters(band="NoExiste"),
    ScoringFilters(min_score=101),
]


@pytest.mark.parametrize("filtros", _FILTROS, ids=lambda f: f.model_dump_json(exclude_none=True))
def test_get_scoring_top_n_identico(filtros: ScoringFilters):
    filas = _filas_lejos_de_medianoche(300, semilla=21)
    with _entorno(
        filas, perfil=_PERFIL, tecnica={f["id_externo"]: 0.8 for f in filas[::3]}, tasas=_TASAS
    ):
        nuevo = sc_mod.get_scoring(filtros, user_key="u-1", organization_id=4, user_id=9)
        antes = _oraculo(filtros, user_key="u-1", organization_id=4, user_id=9)
    assert nuevo.model_dump_json() == antes.model_dump_json()


def test_el_corte_dentro_de_un_empate_desempata_por_orden_de_llegada():
    """`limit` partiendo un grupo de scores iguales: entran los que llegaron antes.

    El corte se elige sobre el ranking real para que caiga dentro de un empate;
    con 300 filas y 101 scores posibles siempre hay uno.
    """
    filas = _filas_lejos_de_medianoche(300, semilla=21)
    with _entorno(filas, perfil=_PERFIL, tecnica={}, tasas=_TASAS):
        todas = sc_mod.get_scoring(ScoringFilters(limit=500), user_key="u-1", organization_id=4)
        scores = [o.score for o in todas.opportunities]
        corte = next(k for k in range(1, len(scores)) if scores[k - 1] == scores[k])
        filtros = ScoringFilters(limit=corte)
        nuevo = sc_mod.get_scoring(filtros, user_key="u-1", organization_id=4)
        antes = _oraculo(filtros, user_key="u-1", organization_id=4)
    assert nuevo.model_dump_json() == antes.model_dump_json()


@pytest.mark.parametrize(
    ("perfil", "tecnica", "tasas"),
    [
        (None, None, None),
        (_PERFIL, {}, {}),
        ({**_PERFIL, "weights": {"importe": 40, "plazo": 30, "competencia": 30}}, {}, _TASAS),
    ],
    ids=["sin_perfil_y_senales_caidas", "perfil_sin_senal_tecnica", "perfil_legado"],
)
def test_get_scoring_con_otros_perfiles_y_senales(perfil, tecnica, tasas):
    filas = _filas_lejos_de_medianoche(150, semilla=33)
    filtros = ScoringFilters(limit=40)
    with _entorno(filas, perfil=perfil, tecnica=tecnica, tasas=tasas, semilla=2):
        nuevo = sc_mod.get_scoring(filtros, user_key="u-2", organization_id=None, user_id=3)
        antes = _oraculo(filtros, user_key="u-2", organization_id=None, user_id=3)
    assert nuevo.model_dump_json() == antes.model_dump_json()


def test_get_scoring_modo_ids_identico():
    """Page-aligned: todas las filas pedidas, en el orden del repositorio, sin cortes."""
    filas = _filas_lejos_de_medianoche(120, semilla=8)
    pedidos = [filas[i]["id_externo"] for i in (90, 3, 3, 57, 12)] + ["NO-EXISTE"]
    filtros = ScoringFilters(ids=pedidos, min_score=99, limit=1, band="Caliente")
    with _entorno(filas, perfil=_PERFIL, tecnica={}, tasas=_TASAS):
        nuevo = sc_mod.get_scoring(filtros, user_key="u-3", organization_id=4)
        antes = _oraculo(filtros, user_key="u-3", organization_id=4)
    assert nuevo.model_dump_json() == antes.model_dump_json()
    assert nuevo.total_scored == 4


def test_get_scoring_con_descartes_identico():
    filas = _filas_lejos_de_medianoche(120, semilla=13)
    descartes = [filas[i]["id_externo"] for i in range(0, 120, 7)]
    filtros = ScoringFilters(limit=10, exclude_dismissed=True)
    with _entorno(filas, perfil=_PERFIL, tecnica={}, tasas=_TASAS, descartes=descartes):
        nuevo = sc_mod.get_scoring(filtros, user_key="u-4", organization_id=4)
        antes = _oraculo(filtros, user_key="u-4", organization_id=4)
    assert nuevo.model_dump_json() == antes.model_dump_json()


@pytest.mark.parametrize("contexto", ["completo", "sin_senales", "legado", "semantico"])
def test_get_scoring_con_hora_fijada_en_los_bordes_del_plazo(contexto: str):
    """Mismo contexto (hora fijada) para los dos: los bordes a un segundo cuentan."""
    ctx = _contextos(_df(_LOTE), semilla=17)[contexto]
    with (
        _entorno(_LOTE, perfil=None, tecnica={}, tasas={}),
        patch.object(sc_mod, "_build_context", return_value=ctx),
    ):
        for filtros in (ScoringFilters(limit=500), ScoringFilters(limit=13)):
            nuevo = sc_mod.get_scoring(filtros)
            antes = _get_scoring_por_filas(filtros)
            assert nuevo.model_dump_json() == antes.model_dump_json()


@pytest.mark.parametrize("contexto", ["completo", "sin_senales"])
def test_score_dataframe_identico(contexto: str):
    """El camino de pipeline y órgano: sin perfil, solo score y banda."""
    df = _df(_LOTE)
    # Como lo llama `pipeline.py`: un subconjunto con índice no contiguo.
    df = df[df.index % 3 != 0]
    ctx = _contextos(df, semilla=19)[contexto]
    with patch.object(sc_mod, "_build_context", return_value=ctx):
        nuevo = sc_mod.score_dataframe(df, df)
        antes = _score_dataframe_por_filas(df, df)
    pd.testing.assert_frame_equal(nuevo, antes, check_dtype=True)
    vacio = sc_mod.score_dataframe(df, df.iloc[0:0])
    pd.testing.assert_frame_equal(vacio, _score_dataframe_por_filas(df, df.iloc[0:0]))


# ---------------------------------------------------------------------------
# Las piezas numéricas, contra Python valor a valor
# ---------------------------------------------------------------------------


def _mismos_bits(obtenido: np.ndarray, esperado: list[float]) -> None:
    esperado_arr = np.array(esperado, dtype=np.float64)
    nan_obtenido, nan_esperado = np.isnan(obtenido), np.isnan(esperado_arr)
    assert (nan_obtenido == nan_esperado).all()
    distintos = np.flatnonzero(
        obtenido[~nan_obtenido].view(np.int64) != esperado_arr[~nan_esperado].view(np.int64)
    )
    assert distintos.size == 0, [
        (float(obtenido[~nan_obtenido][i]), esperado_arr[~nan_esperado][i]) for i in distintos[:10]
    ]


def _valores_frontera() -> list[float]:
    """Valores a medio céntimo de un empate y sus vecinos a pocos ulps."""
    valores: list[float] = []
    for k in range(-2_000, 12_000):
        base = k / 100 + 0.005
        valores.append(base)
        arriba = abajo = base
        for _ in range(3):
            arriba = math.nextafter(arriba, math.inf)
            abajo = math.nextafter(abajo, -math.inf)
            valores.extend((arriba, abajo))
    return valores


def test_redondear_2_es_round_de_python_bit_a_bit():
    rng = np.random.default_rng(2026)
    fracciones = np.linspace(0.0, 1.0, 1_001)
    productos = [f * w for f in fracciones.tolist() for w in range(0, 101, 3)]
    especiales = [
        0.0,
        -0.0,
        -0.001,
        0.004,
        0.005,
        0.015,
        0.025,
        1.005,
        2.675,
        7.125,
        12.5,
        10.5,
        14.499999999999998,
        math.nan,
        math.inf,
        -math.inf,
        1e300,
        -1e300,
        2.0**52 / 100,
        2.0**53,
        5e-324,
    ]
    valores = [
        *rng.uniform(-100, 200, 50_000).tolist(),
        *np.round(rng.uniform(0, 100, 20_000), 3).tolist(),
        *productos,
        *_valores_frontera(),
        *especiales,
    ]
    obtenido = sc_mod._redondear_2(np.array(valores, dtype=np.float64))
    _mismos_bits(obtenido, [round(v, 2) for v in valores])


def test_np_round_no_serviria():
    """Guardia del helper: si `np.round` coincidiera con `round`, sobraría."""
    frontera = np.array(_valores_frontera(), dtype=np.float64)
    assert (np.round(frontera, 2) != np.array([round(v, 2) for v in frontera.tolist()])).any()


def test_sumar_como_python_es_sum_bit_a_bit():
    rng = random.Random(99)
    for sumandos in (4, 5, 6):
        filas: list[list[float]] = []
        for _ in range(4_000):
            filas.append([round(rng.uniform(0, 30), 2) for _ in range(sumandos)])
            filas.append(
                [rng.uniform(-1e3, 1e3) * 10 ** rng.randint(-8, 8) for _ in range(sumandos)]
            )
        filas.append([0.1, 0.2, 0.3, 0.4, 0.5, 0.6][:sumandos])
        filas.append([1e16, 1.0, -1e16, 3.5, 2.25, 0.125][:sumandos])
        filas.append([-0.0] * sumandos)
        filas.append([12.35, 10.15, 7.5, 12.5, 0.0, 0.0][:sumandos])
        columnas = [np.array(col, dtype=np.float64) for col in zip(*filas, strict=True)]
        obtenido = sc_mod._sumar_como_python(columnas)
        _mismos_bits(obtenido, [sum(fila) for fila in filas])


@pytest.mark.skipif(sys.version_info < (3, 12), reason="la sum compensada llega en 3.12")
def test_sum_de_python_es_compensada():
    """Guardia del helper: con una suma ingenua bastaría `np.sum`."""
    assert sum([0.1, 0.2, 0.3]) != (0.1 + 0.2) + 0.3


def test_score_entero_es_max_min_round_de_python():
    totales = [
        -5.5,
        -0.5,
        -0.0,
        0.5,
        1.5,
        2.5,
        24.5,
        49.5,
        50.5,
        74.5,
        99.5,
        100.5,
        101.0,
        1e9,
        *np.random.default_rng(1).uniform(-20, 130, 5_000).tolist(),
    ]
    obtenido = sc_mod._score_entero(np.array(totales, dtype=np.float64))
    assert obtenido.tolist() == [max(0, min(round(t), 100)) for t in totales]


@pytest.mark.parametrize("valor", [math.nan, math.inf, -math.inf])
def test_score_entero_no_finito_lanza_lo_mismo_que_round(valor: float):
    with pytest.raises(Exception) as esperado:
        round(valor)
    with pytest.raises(type(esperado.value), match=str(esperado.value)):
        sc_mod._score_entero(np.array([10.0, valor], dtype=np.float64))


def test_acotar_01_es_max_min_de_python():
    valores = [math.nan, -0.0, 0.0, 1.0, 1.0000000000000002, 0.9999999999999999, -1e-300]
    valores += [math.inf, -math.inf, 0.5, 2.0, -2.0]
    obtenido = sc_mod._acotar_01(np.array(valores, dtype=np.float64))
    _mismos_bits(obtenido, [max(0.0, min(1.0, v)) for v in valores])


# ---------------------------------------------------------------------------
# Afinidad por columnas contra la de iterrows
# ---------------------------------------------------------------------------

_PORTFOLIOS = {
    "keywords": build_portfolio(keywords=["erp", "soporte", "mantenimiento", "sap"]),
    "cpvs": build_portfolio(cpvs=["72260000", "48000000"]),
    "contratos": build_portfolio(contracts=["Ayuntamiento · SAP · EXP-1"]),
    "todo": build_portfolio(
        keywords=["erp", "gestión económica"], cpvs=["72000000"], contracts=["Soporte ERP"]
    ),
}


def _df_afinidad(columnas_fuera: tuple[str, ...]) -> pd.DataFrame:
    df = pd.DataFrame(_LOTE[:150])
    # Un id repetido: el dict del resultado se queda con la última, en los dos.
    df.loc[10, "id_externo"] = df.loc[3, "id_externo"]
    return df.drop(columns=list(columnas_fuera))


def _vectores_deterministas(textos: list[str], **_k: Any) -> np.ndarray:
    """Embeddings falsos pero estables: mismo texto, mismo vector."""
    filas = []
    for texto in textos:
        rng = np.random.default_rng(abs(hash(texto)) % (2**32))
        vector = rng.normal(size=8)
        filas.append(vector / np.linalg.norm(vector))
    return np.array(filas)


@pytest.mark.parametrize("portfolio", list(_PORTFOLIOS), ids=list(_PORTFOLIOS))
@pytest.mark.parametrize("columnas_fuera", [(), ("descripcion",), ("cpv", "titulo")])
@pytest.mark.parametrize("embeddings", [False, True])
def test_afinidad_por_columnas_identica(portfolio, columnas_fuera, embeddings):
    df = _df_afinidad(columnas_fuera)
    cartera = _PORTFOLIOS[portfolio]
    textos: dict[str, list[list[str]]] = {"nuevo": [], "antes": []}

    def _codificar(destino: str):
        def _encode(textos_pedidos: list[str], **kwargs: Any) -> np.ndarray:
            textos[destino].append(list(textos_pedidos))
            return _vectores_deterministas(textos_pedidos)

        return _encode

    with patch("services.embeddings.embeddings_available", return_value=embeddings):
        with patch("services.embeddings.encode_texts", side_effect=_codificar("nuevo")):
            nuevo = af_mod.score_affinity_batch(df, cartera)
        with patch("services.embeddings.encode_texts", side_effect=_codificar("antes")):
            antes = _score_affinity_batch_por_filas(df, cartera)

    assert nuevo == antes
    assert textos["nuevo"] == textos["antes"]


def test_afinidad_sin_columna_de_ids_revienta_igual_que_antes():
    df = pd.DataFrame(_LOTE[:5]).drop(columns=["id_externo"])
    cartera = _PORTFOLIOS["keywords"]
    with pytest.raises(ValueError) as antes:
        _score_affinity_batch_por_filas(df, cartera)
    with pytest.raises(ValueError) as ahora:
        af_mod.score_affinity_batch(df, cartera)
    assert type(ahora.value) is type(antes.value)
