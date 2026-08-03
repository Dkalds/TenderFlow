"""Tests for the Opportunity scoring service.

Cubre los dos modos del endpoint /api/v1/analytics/scoring:

- top-N (por defecto, lo usa Tecnologias): ranking por score, truncado a limit.
- page-aligned por ids (lo usa el listado de Detalle): puntua EXACTAMENTE las
  filas visibles, ignorando min_score/band/limit, con la misma normalizacion
  global P10/P90 para que el score este siempre alineado con lo que se ve
  (ADR-014: el backend es la fuente, el front solo alinea por id).

Data access mockeado en load_stats_dataframe y en los loaders de senales
(load_competencia_stats, load_margen_stats) sin dependencia de BD.
Los loaders de senales se parchean sobre el modulo scoring (donde estan
importados por nombre) para que los mocks sean efectivos.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pandas as pd
import pytest

import services.analytics.scoring as sc_mod
from services.analytics.scoring import _effective_weights, score_dataframe
from services.analytics.scoring_signals import CompetenciaStats, MargenStats

# ---------------------------------------------------------------------------
# Helpers de fixtures
# ---------------------------------------------------------------------------

_EMPTY_COMP = CompetenciaStats()
_EMPTY_MARG = MargenStats()


# ---------------------------------------------------------------------------
# Doble del repositorio (ADR-023): get_scoring ya no carga la tabla a pandas —
# lee proyecciones acotadas de AggregateRepository. Este helper alimenta esas
# tres llamadas desde las mismas filas sintéticas, calculando P10/P90 con la
# misma interpolación (lineal) que usaba el pandas original.
# ---------------------------------------------------------------------------

_PROJ_KEYS = (
    "id_externo",
    "titulo",
    "organo_contratacion",
    "importe",
    "cpv",
    "fecha_limite",
    "estado",
    "ccaa",
    "tecnologia",
    "fecha_publicacion",
)


@contextmanager
def _repo_data(rows: list[dict]):
    normalized = [{k: r.get(k) for k in _PROJ_KEYS} for r in rows]
    imp = pd.Series([r.get("importe") for r in normalized], dtype=float).dropna()
    p10 = float(imp.quantile(0.10)) if len(imp) else 0.0
    p90 = float(imp.quantile(0.90)) if len(imp) else 0.0

    def _by_ids(ids: list[str]) -> list[dict]:
        wanted = {str(i) for i in ids}
        return [r for r in normalized if str(r.get("id_externo")) in wanted]

    with ExitStack() as stack:
        stack.enter_context(
            patch.object(sc_mod._repo, "scoring_candidates", return_value=normalized)
        )
        stack.enter_context(patch.object(sc_mod._repo, "licitaciones_by_ids", side_effect=_by_ids))
        stack.enter_context(
            patch.object(sc_mod._repo, "importe_percentiles", return_value=(p10, p90))
        )
        yield


def _patch_signals(comp: CompetenciaStats = _EMPTY_COMP, marg: MargenStats = _EMPTY_MARG):
    """Mockea los loaders de señales en el namespace de scoring (donde están bound)."""
    return (
        patch.object(sc_mod, "load_competencia_stats", return_value=comp),
        patch.object(sc_mod, "load_margen_stats", return_value=marg),
    )


def _rows(n: int = 30) -> list[dict]:
    rows: list[dict] = []
    for i in range(n):
        rows.append(
            {
                "id_externo": f"L{i:03d}",
                "titulo": (
                    "Contrato de consultoría y soporte técnico"
                    if i % 2
                    else "Servicio generico de limpieza"
                ),
                "organo_contratacion": f"Organo {i % 3}",
                "importe": float(10_000 * (i + 1)),
                "estado": "PUB",
                "ccaa": "Madrid",
                "tecnologia": "SAP",
                "cpv": "72000000",
                "fecha_publicacion": "2026-03-01T00:00:00+00:00",
                "fecha_limite": "2026-04-15T00:00:00+00:00",
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Tests existentes (conservados, ampliar parches para los nuevos loaders)
# ---------------------------------------------------------------------------


def test_scoring_top_n_ranks_and_truncates():
    """Modo por defecto: ordenado por score desc y truncado a limit."""
    comp, marg = _patch_signals()
    with (
        _repo_data(_rows(30)),
        comp,
        marg,
    ):
        res = sc_mod.get_scoring(sc_mod.ScoringFilters(limit=5))
    assert len(res.opportunities) == 5
    scores = [o.score for o in res.opportunities]
    assert scores == sorted(scores, reverse=True)


def test_scoring_ids_returns_exactly_requested_rows():
    """Modo page-aligned: exactamente las filas pedidas, ignorando min_score/limit."""
    requested = ["L005", "L020", "L029", "L002"]
    comp, marg = _patch_signals()
    with (
        _repo_data(_rows(30)),
        comp,
        marg,
    ):
        res = sc_mod.get_scoring(sc_mod.ScoringFilters(ids=requested, min_score=99, limit=1))
    got = {o.id_externo for o in res.opportunities}
    assert got == set(requested)
    # min_score=99 y limit=1 NO deben recortar en modo ids.
    assert len(res.opportunities) == 4


def test_scoring_ids_normalization_matches_global():
    """El score de una fila es idéntico en top-N y en ids-mode (P10/P90 global)."""
    comp, marg = _patch_signals()
    with (
        _repo_data(_rows(30)),
        comp,
        marg,
    ):
        full = {
            o.id_externo: o.score
            for o in sc_mod.get_scoring(sc_mod.ScoringFilters(limit=500)).opportunities
        }
    comp2, marg2 = _patch_signals()
    with (
        _repo_data(_rows(30)),
        comp2,
        marg2,
    ):
        one = {
            o.id_externo: o.score
            for o in sc_mod.get_scoring(sc_mod.ScoringFilters(ids=["L005"])).opportunities
        }
    assert one["L005"] == full["L005"]


def test_scoring_ids_unknown_is_empty():
    comp, marg = _patch_signals()
    with (
        _repo_data(_rows(10)),
        comp,
        marg,
    ):
        res = sc_mod.get_scoring(sc_mod.ScoringFilters(ids=["NOPE", "ZZZ"]))
    assert res.opportunities == []


def test_scoring_empty_dataset():
    comp, marg = _patch_signals()
    with _repo_data([]), comp, marg:
        res = sc_mod.get_scoring(sc_mod.ScoringFilters(ids=["L000"]))
    assert res.opportunities == []
    assert res.total_scored == 0


# ---------------------------------------------------------------------------
# Nuevos tests: competencia
# ---------------------------------------------------------------------------


def test_competencia_less_competitive_scores_higher():
    """Segmento con 2 ofertas medias debe superar al de 9 en competencia."""
    # CPV "7200" → 2 ofertas: fracción = 1 - (2-1)/9 ≈ 0.89
    # CPV "3300" → 9 ofertas: fracción = 1 - (9-1)/9 ≈ 0.11
    comp = CompetenciaStats(media_por_cpv4={"7200": 2.0, "3300": 9.0})
    marg = MargenStats()

    row_low_comp = {
        "id_externo": "A001",
        "titulo": "Servicio TI",
        "organo_contratacion": "Org1",
        "importe": 100_000.0,
        "cpv": "72000000",
        "fecha_limite": "2026-04-15T00:00:00+00:00",
    }
    row_high_comp = {
        "id_externo": "A002",
        "titulo": "Servicio Industrial",
        "organo_contratacion": "Org1",
        "importe": 100_000.0,
        "cpv": "33000000",
        "fecha_limite": "2026-04-15T00:00:00+00:00",
    }
    with (
        _repo_data([row_low_comp, row_high_comp]),
        patch.object(sc_mod, "load_competencia_stats", return_value=comp),
        patch.object(sc_mod, "load_margen_stats", return_value=marg),
    ):
        res = sc_mod.get_scoring(sc_mod.ScoringFilters(limit=10))
    by_id = {o.id_externo: o for o in res.opportunities}
    assert by_id["A001"].desglose["competencia"] > by_id["A002"].desglose["competencia"]


def test_competencia_fallback_global():
    """CPV sin datos → usa media global."""
    comp = CompetenciaStats(media_por_cpv4={}, media_global=3.0)
    marg = MargenStats()
    row = {
        "id_externo": "B001",
        "titulo": "Obra desconocida",
        "importe": 50_000.0,
        "cpv": "99999999",
    }
    with (
        _repo_data([row]),
        patch.object(sc_mod, "load_competencia_stats", return_value=comp),
        patch.object(sc_mod, "load_margen_stats", return_value=marg),
    ):
        res = sc_mod.get_scoring(sc_mod.ScoringFilters(limit=10))
    opp = res.opportunities[0]
    assert opp.desglose["competencia"] > 0
    assert "sin_historico_competencia" not in opp.risk_flags


def test_competencia_neutral_sin_datos():
    """Sin stats de competencia -> neutral (=50% del peso efectivo) + flag."""
    comp = CompetenciaStats()  # todo vacio
    marg = MargenStats()
    row = {
        "id_externo": "C001",
        "titulo": "Algo",
        "importe": 50_000.0,
        "cpv": "72000000",
    }
    with (
        _repo_data([row]),
        patch.object(sc_mod, "load_competencia_stats", return_value=comp),
        patch.object(sc_mod, "load_margen_stats", return_value=marg),
    ):
        res = sc_mod.get_scoring(sc_mod.ScoringFilters(limit=10))
    opp = res.opportunities[0]
    # Neutro = 50% del peso efectivo de competencia.
    # Con afinidad vacia (default), los pesos se redistribuyen: competencia efectivo = 29.
    # 29 * 0.5 = 14.5
    assert opp.desglose["competencia"] > 0
    assert opp.desglose["competencia"] < opp.desglose["competencia"] * 2  # sanity
    # Lo importante: siempre menor que el maximo posible (peso efectivo)
    from config import settings
    from services.analytics.scoring import _effective_weights

    eff = _effective_weights(
        dict(settings.SCORING_WEIGHTS), list(settings.SCORING_AFINIDAD_KEYWORDS)
    )
    max_comp = eff.get("competencia", 25)
    assert opp.desglose["competencia"] == pytest.approx(max_comp * 0.5, abs=0.1)
    assert "sin_historico_competencia" in opp.risk_flags


# ---------------------------------------------------------------------------
# Nuevos tests: margen
# ---------------------------------------------------------------------------


def test_margen_low_baja_scores_higher():
    """Baja esperada baja (p50=0.05) debe dar más puntos que baja alta (p50=0.35)."""
    marg = MargenStats(p50_por_licitacion={"M001": 0.05, "M002": 0.35})
    comp = CompetenciaStats()

    rows = [
        {"id_externo": "M001", "titulo": "TI", "importe": 100_000.0, "cpv": "72000000"},
        {"id_externo": "M002", "titulo": "TI2", "importe": 100_000.0, "cpv": "72000000"},
    ]
    with (
        _repo_data(rows),
        patch.object(sc_mod, "load_competencia_stats", return_value=comp),
        patch.object(sc_mod, "load_margen_stats", return_value=marg),
    ):
        res = sc_mod.get_scoring(sc_mod.ScoringFilters(limit=10))
    by_id = {o.id_externo: o for o in res.opportunities}
    assert by_id["M001"].desglose["margen"] > by_id["M002"].desglose["margen"]


def test_margen_fallback_cpv4():
    """Sin p50 para la licitación → fallback a baja media CPV-4."""
    marg = MargenStats(baja_media_por_cpv4={"7200": 0.10})
    comp = CompetenciaStats()
    row = {"id_externo": "N001", "titulo": "TI", "importe": 50_000.0, "cpv": "72000000"}
    with (
        _repo_data([row]),
        patch.object(sc_mod, "load_competencia_stats", return_value=comp),
        patch.object(sc_mod, "load_margen_stats", return_value=marg),
    ):
        res = sc_mod.get_scoring(sc_mod.ScoringFilters(limit=10))
    opp = res.opportunities[0]
    assert opp.desglose["margen"] > 0
    assert "sin_prediccion" not in opp.risk_flags


def test_margen_sin_prediccion_flag():
    """Sin ningun dato de baja -> neutral + flag sin_prediccion."""
    marg = MargenStats()
    comp = CompetenciaStats()
    row = {"id_externo": "P001", "titulo": "TI", "importe": 50_000.0, "cpv": "72000000"}
    with (
        _repo_data([row]),
        patch.object(sc_mod, "load_competencia_stats", return_value=comp),
        patch.object(sc_mod, "load_margen_stats", return_value=marg),
    ):
        res = sc_mod.get_scoring(sc_mod.ScoringFilters(limit=10))
    opp = res.opportunities[0]
    # Neutro = 50% del peso efectivo de margen (puede ser redistribuido si no hay afinidad)
    from config import settings
    from services.analytics.scoring import _effective_weights

    eff = _effective_weights(
        dict(settings.SCORING_WEIGHTS), list(settings.SCORING_AFINIDAD_KEYWORDS)
    )
    max_margen = eff.get("margen", 20)
    assert opp.desglose["margen"] == pytest.approx(max_margen * 0.5, abs=0.1)
    assert "sin_prediccion" in opp.risk_flags


# ---------------------------------------------------------------------------
# Nuevos tests: afinidad
# ---------------------------------------------------------------------------


def test_afinidad_con_keywords_matchea_mas(monkeypatch):
    """Con keywords configuradas, fila que las contiene tiene más afinidad."""
    monkeypatch.setattr("config.settings.SCORING_AFINIDAD_KEYWORDS", ["consultoría", "soporte"])
    comp = CompetenciaStats()
    marg = MargenStats()
    rows = [
        {
            "id_externo": "AF01",
            "titulo": "Contrato de consultoría y soporte",
            "importe": 50_000.0,
            "cpv": "72000000",
        },
        {
            "id_externo": "AF02",
            "titulo": "Limpieza de oficinas",
            "importe": 50_000.0,
            "cpv": "72000000",
        },
    ]
    with (
        _repo_data(rows),
        patch.object(sc_mod, "load_competencia_stats", return_value=comp),
        patch.object(sc_mod, "load_margen_stats", return_value=marg),
    ):
        res = sc_mod.get_scoring(sc_mod.ScoringFilters(limit=10))
    by_id = {o.id_externo: o for o in res.opportunities}
    assert "afinidad" in by_id["AF01"].desglose
    assert by_id["AF01"].desglose["afinidad"] > by_id["AF02"].desglose["afinidad"]


def test_afinidad_lista_vacia_omite_key(monkeypatch):
    """Con lista vacía, la key 'afinidad' NO aparece en el desglose."""
    monkeypatch.setattr("config.settings.SCORING_AFINIDAD_KEYWORDS", [])
    comp = CompetenciaStats()
    marg = MargenStats()
    row = {"id_externo": "AF03", "titulo": "Algo", "importe": 50_000.0, "cpv": "72000000"}
    with (
        _repo_data([row]),
        patch.object(sc_mod, "load_competencia_stats", return_value=comp),
        patch.object(sc_mod, "load_margen_stats", return_value=marg),
    ):
        res = sc_mod.get_scoring(sc_mod.ScoringFilters(limit=10))
    opp = res.opportunities[0]
    assert "afinidad" not in opp.desglose


# ---------------------------------------------------------------------------
# Nuevos tests: _effective_weights
# ---------------------------------------------------------------------------


def test_effective_weights_con_keywords_suma_100():
    weights = {"importe": 25, "plazo": 15, "competencia": 25, "margen": 20, "afinidad": 15}
    eff = _effective_weights(weights, ["consultoría"])
    assert sum(eff.values()) == 100
    assert "afinidad" in eff


def test_effective_weights_sin_keywords_redistribuye():
    weights = {"importe": 25, "plazo": 15, "competencia": 25, "margen": 20, "afinidad": 15}
    eff = _effective_weights(weights, [])
    assert sum(eff.values()) == 100
    assert "afinidad" not in eff


def test_effective_weights_sin_afinidad_key_suma_100():
    """Si 'afinidad' no está en los pesos, devuelve tal cual."""
    weights = {"importe": 40, "plazo": 30, "competencia": 30}
    eff = _effective_weights(weights, [])
    assert sum(eff.values()) == 100


# ---------------------------------------------------------------------------
# Nuevos tests: riesgo máximo
# ---------------------------------------------------------------------------


def test_riesgo_max_tres_flags():
    """Fila sin importe, sin título y sin fecha_limite acumula -10 de riesgo."""
    comp = CompetenciaStats()
    marg = MargenStats()
    row = {
        "id_externo": "R001",
        "titulo": "",  # sin título
        "importe": None,  # sin importe
        "cpv": "72000000",
        # sin fecha_limite → flag sin_plazo
    }
    with (
        _repo_data([row]),
        patch.object(sc_mod, "load_competencia_stats", return_value=comp),
        patch.object(sc_mod, "load_margen_stats", return_value=marg),
    ):
        res = sc_mod.get_scoring(sc_mod.ScoringFilters(limit=10))
    opp = res.opportunities[0]
    assert opp.desglose["riesgo"] == pytest.approx(-10.0, abs=0.01)
    assert "sin_importe" in opp.risk_flags
    assert "sin_titulo" in opp.risk_flags
    assert "sin_plazo" in opp.risk_flags


# ---------------------------------------------------------------------------
# score_dataframe — helper público sin perfil de usuario (usado por
# services/analytics/pipeline.py para poblar score/band en /analytics/pipeline)
# ---------------------------------------------------------------------------


def test_score_dataframe_target_vacio_devuelve_columnas_vacias():
    comp, marg = _patch_signals()
    with comp, marg:
        out = score_dataframe(pd.DataFrame(_rows(5)), pd.DataFrame([]))
    assert list(out.columns) == ["id_externo", "score", "band"]
    assert out.empty


def test_score_dataframe_devuelve_id_score_band_por_fila():
    comp, marg = _patch_signals()
    rows = _rows(5)
    with comp, marg:
        out = score_dataframe(pd.DataFrame(rows), pd.DataFrame(rows))
    assert set(out.columns) >= {"id_externo", "score", "band"}
    assert len(out) == 5
    assert set(out["id_externo"]) == {r["id_externo"] for r in rows}
    assert out["band"].isin(["Caliente", "Atractiva", "Tibia", "Descarte"]).all()


def test_score_dataframe_coincide_con_get_scoring_para_la_misma_fila():
    """score_dataframe (sin perfil) debe dar el mismo score que get_scoring top-N
    para la misma fila y el mismo dataset base — ambos usan _build_context/_score_row
    sin perfil de usuario.

    Sin "fecha_limite" en las filas: get_scoring solo parsea fecha_limite_dt si
    la columna existe, y score_dataframe (a diferencia de get_scoring) no hace
    ningún parseo de fechas por su cuenta — lo evitamos aquí para comparar
    manzanas con manzanas (ver test_pipeline_score_y_band_poblados_en_upcoming
    en test_analytics_pipeline_svc.py para la integración real con fechas).
    """
    comp, marg = _patch_signals()
    rows = [{k: v for k, v in r.items() if k != "fecha_limite"} for r in _rows(10)]
    with (
        _repo_data(rows),
        comp,
        marg,
    ):
        scoring_result = sc_mod.get_scoring(sc_mod.ScoringFilters(limit=500))
    scoring_scores = {o.id_externo: o.score for o in scoring_result.opportunities}

    comp2, marg2 = _patch_signals()
    with comp2, marg2:
        out = score_dataframe(pd.DataFrame(rows), pd.DataFrame(rows))
    df_scores = dict(zip(out["id_externo"], out["score"], strict=True))

    assert df_scores == scoring_scores


def test_score_dataframe_usa_contexto_del_base_df_no_del_target():
    """Los percentiles P10/P90 de importe se calculan sobre base_df completo,
    no sobre el target_df (que puede ser un subconjunto ya filtrado)."""
    comp, marg = _patch_signals()
    base_rows = _rows(30)  # importes 10_000..300_000 -> P10/P90 amplios
    target = [base_rows[0]]  # una sola fila, importe bajo dentro del rango base

    with comp, marg:
        out_wide_ctx = score_dataframe(pd.DataFrame(base_rows), pd.DataFrame(target))

    # Si el contexto se calculara sobre target_df (1 fila), P10==P90 y el caso
    # "sin rango" daría un score distinto (dimensión importe → 50% neutral).
    narrow_comp, narrow_marg = _patch_signals()
    with narrow_comp, narrow_marg:
        out_narrow_ctx = score_dataframe(pd.DataFrame(target), pd.DataFrame(target))

    assert out_wide_ctx["score"].iloc[0] != out_narrow_ctx["score"].iloc[0]


# ---------------------------------------------------------------------------
# Guardia: no deben existir constantes SAP en el módulo scoring
# ---------------------------------------------------------------------------


def test_no_sap_constants_in_scoring_module():
    """El módulo scoring NO debe contener _SAP_MODULES, _SAP_SERVICES_PORTFOLIO
    ni _S4HANA_KEYWORDS."""
    assert not hasattr(sc_mod, "_SAP_MODULES")
    assert not hasattr(sc_mod, "_SAP_SERVICES_PORTFOLIO")
    assert not hasattr(sc_mod, "_S4HANA_KEYWORDS")
