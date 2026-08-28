"""La salud competitiva no publica un porcentaje sin decir sobre cuántas filas va.

En producción la tira «Salud competitiva» del Resumen servía «oferta única
93,1 %» y «PYME adjudicataria 0,7 %». Ninguna de las dos es una medida del
mercado español: son el reparto de qué adjudicaciones traen
``n_ofertas_recibidas`` y ``es_pyme``. Estos tests fijan la regla que evita
volver ahí — **el valor viaja con su base, y una base que no se ha medido no
autoriza a afirmar el valor** — y, sobre todo, que una cobertura baja se
reporta con su número real y no se maquilla redondeándola.

Van sin Postgres a propósito: lo que se está fijando es la política de
cobertura, no la agregación SQL (esa la cubre ``test_analytics_overview.py``).
"""

from __future__ import annotations

from typing import Any

import pytest

from services.analytics import overview as ov
from shared.dto import CoberturaMetricaDTO

# ---------------------------------------------------------------------------
# `_cobertura`: base + universo -> veredicto
# ---------------------------------------------------------------------------


def test_cobertura_desconocida_no_autoriza_a_afirmar() -> None:
    """Sin base medida, `suficiente` es False — el default seguro."""
    cobertura = ov._cobertura(None, 170_000)
    assert cobertura.cobertura_pct is None
    assert cobertura.base is None
    assert cobertura.suficiente is False


def test_universo_cero_no_es_cobertura_total() -> None:
    """0/0 no es «lo tenemos todo»: es que no hay corpus que medir."""
    cobertura = ov._cobertura(0, 0)
    assert cobertura.cobertura_pct is None
    assert cobertura.suficiente is False


def test_cobertura_baja_llega_con_su_cifra_real() -> None:
    """El caso del hallazgo: 5.780 de 170.000 filas traen el dato.

    Lo que no puede pasar es que el backend redondee ese 3,4 % a un número
    cómodo (0, «bajo», o el propio umbral): quien recibe la métrica tiene que
    poder decir *cuánto* de poco es. Que sea insuficiente lo dice `suficiente`,
    no una cifra amputada.
    """
    cobertura = ov._cobertura(5_780, 170_000)
    assert cobertura.suficiente is False
    assert cobertura.base == 5_780
    assert cobertura.universo == 170_000
    assert cobertura.cobertura_pct == pytest.approx(3.4)


def test_cobertura_justo_bajo_el_umbral_sigue_siendo_insuficiente() -> None:
    cobertura = ov._cobertura(4_999, 10_000)
    assert cobertura.cobertura_pct == pytest.approx(49.99)
    assert cobertura.suficiente is False


def test_cobertura_en_el_umbral_es_suficiente() -> None:
    """El umbral es inclusivo y viaja con el dato, no se reinventa en cliente."""
    cobertura = ov._cobertura(5_000, 10_000)
    assert cobertura.cobertura_pct == pytest.approx(50.0)
    assert cobertura.umbral_pct == ov.UMBRAL_COBERTURA_PCT
    assert cobertura.suficiente is True


def test_dto_por_defecto_se_abstiene() -> None:
    """Un cliente que construya el DTO vacío no acaba afirmando nada."""
    assert CoberturaMetricaDTO().suficiente is False
    assert CoberturaMetricaDTO().cobertura_pct is None


# ---------------------------------------------------------------------------
# Cableado en `get_overview`
# ---------------------------------------------------------------------------


class _RepoFalso:
    """Repositorio mínimo: solo devuelve formas válidas.

    Lo único que varía entre tests es el dict de indicadores de adjudicaciones,
    que es donde vive la cobertura; el resto son constantes para que el fallo,
    si lo hay, señale a la cobertura y no al ruido de alrededor.
    """

    def __init__(self, adj: dict[str, float | None]) -> None:
        self._adj = adj

    def overview_adjudicaciones_indicadores(self) -> dict[str, float | None]:
        return self._adj

    def overview_kpis(self, _filters: Any) -> dict[str, Any]:
        return {"total": 10, "importe_total": 1000.0, "importe_medio": 100.0, "organos": 3}

    def overview_yoy_and_recent(self, _filters: Any, **_kw: Any) -> dict[str, float]:
        return {"lics_30d": 4.0, "lics_prev30d": 2.0, "importe_30d": 400.0}

    def overview_concentracion_organos(self, _filters: Any, **_kw: Any) -> tuple[float, float]:
        return (600.0, 1000.0)

    def overview_tasa_anulacion(self, _filters: Any, **_kw: Any) -> tuple[int, int]:
        return (1, 10)

    def overview_concentracion_ccaa(self, _filters: Any, **_kw: Any) -> tuple[float, float]:
        return (700.0, 1000.0)

    def overview_ccaa_cubiertas(self, _filters: Any) -> int:
        return 3

    def overview_para_hoy(self, _filters: Any, **_kw: Any) -> dict[str, int]:
        return {"calientes_hoy": 1, "vencen_48h": 2, "nuevas_24h": 3}

    def overview_por_estado(self, _filters: Any) -> list[dict[str, Any]]:
        return []

    def overview_por_mes(self, _filters: Any) -> list[dict[str, Any]]:
        return []

    def overview_top_organos(self, _filters: Any) -> list[dict[str, Any]]:
        return []

    def overview_funnel(self, _filters: Any) -> dict[str, int]:
        return {"total": 10, "PUB": 4, "EV": 2, "RES": 2, "ADJ": 1, "ANUL": 1}


def _montar(monkeypatch: pytest.MonkeyPatch, adj: dict[str, float | None]) -> ov.OverviewResult:
    monkeypatch.setattr(ov, "_repo", _RepoFalso(adj))
    monkeypatch.setattr(ov, "read_overview_snapshot_for", lambda _f, **_kw: None)
    return ov.get_overview(ov.OverviewFilters())


_ADJ_HOY: dict[str, float | None] = {
    # Exactamente lo que el agregado devuelve hoy: los cuatro valores, ninguna base.
    "hhi": 410.0,
    "pct_oferta_unica": 93.1,
    "lead_time_medio": 104.7,
    "pct_pyme": 0.7,
}


def test_sin_bases_el_93_por_ciento_viaja_marcado_como_no_afirmable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El agregado actual no cuenta filas: la cobertura sale desconocida.

    El valor se sigue sirviendo (no romper el contrato existente), pero
    `suficiente=False` es lo que impide que la pantalla lo presente como hecho.
    """
    result = _montar(monkeypatch, dict(_ADJ_HOY))
    assert result.pct_oferta_unica == pytest.approx(93.1)
    assert result.cobertura_oferta_unica.suficiente is False
    assert result.cobertura_oferta_unica.cobertura_pct is None
    assert result.cobertura_pyme.suficiente is False
    assert result.cobertura_pyme.cobertura_pct is None


def test_con_bases_bajas_la_cobertura_se_reporta_sin_maquillar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cuando `db/` empiece a contar filas, el número pequeño llega entero."""
    adj = dict(_ADJ_HOY)
    adj[ov._K_ADJ_TOTAL] = 170_000.0
    adj[ov._K_ADJ_CON_N_OFERTAS] = 5_780.0
    adj[ov._K_ADJ_CON_ES_PYME] = 1_190.0

    result = _montar(monkeypatch, adj)

    assert result.cobertura_oferta_unica.cobertura_pct == pytest.approx(3.4)
    assert result.cobertura_oferta_unica.base == 5_780
    assert result.cobertura_oferta_unica.universo == 170_000
    assert result.cobertura_oferta_unica.suficiente is False
    assert result.cobertura_pyme.cobertura_pct == pytest.approx(0.7)
    assert result.cobertura_pyme.suficiente is False


def test_con_cobertura_alta_la_metrica_queda_habilitada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adj = dict(_ADJ_HOY)
    adj[ov._K_ADJ_TOTAL] = 170_000.0
    adj[ov._K_ADJ_CON_N_OFERTAS] = 150_000.0

    result = _montar(monkeypatch, adj)

    assert result.cobertura_oferta_unica.suficiente is True
    assert result.cobertura_oferta_unica.cobertura_pct == pytest.approx(88.235, abs=1e-3)
    # La PYME no comparte base con las ofertas: sigue sin medir.
    assert result.cobertura_pyme.suficiente is False


def test_fallo_del_agregado_no_inventa_cobertura(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si el agregado revienta, el fallback deja ceros — pero no una cobertura.

    Un 0 % de oferta única con «cobertura suficiente» sería peor que el bug que
    esto viene a arreglar: afirmaría que no existe la oferta única.
    """

    class _RepoRoto(_RepoFalso):
        def overview_adjudicaciones_indicadores(self) -> dict[str, float | None]:
            raise RuntimeError("agregado caído")

    monkeypatch.setattr(ov, "_repo", _RepoRoto({}))
    monkeypatch.setattr(ov, "read_overview_snapshot_for", lambda _f, **_kw: None)
    result = ov.get_overview(ov.OverviewFilters())

    assert result.pct_oferta_unica == 0.0
    assert result.cobertura_oferta_unica.suficiente is False
    assert result.cobertura_pyme.suficiente is False
