"""Tests for the Opportunity scoring service.

Cubre los dos modos del endpoint `/api/v1/analytics/scoring`:

- **top-N** (por defecto, lo usa Tecnologías): ranking por score, truncado a
  ``limit``.
- **page-aligned por ids** (lo usa el listado de Detalle): puntúa EXACTAMENTE las
  filas visibles, ignorando min_score/band/limit, con la misma normalización
  global P10/P90 — para que el score esté siempre alineado con lo que se ve
  (ADR-014: el backend es la fuente, el front solo alinea por id).

Data access mockeado en ``load_stats_dataframe``.
"""

from __future__ import annotations

from unittest.mock import patch

import services.analytics.scoring as sc_mod


def _rows(n: int = 30) -> list[dict]:
    rows: list[dict] = []
    for i in range(n):
        rows.append(
            {
                "id_externo": f"L{i:03d}",
                "titulo": (
                    "Implantacion SAP S/4HANA migracion FI CO"
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


def test_scoring_top_n_ranks_and_truncates():
    """Modo por defecto: ordenado por score desc y truncado a limit."""
    with patch.object(sc_mod, "load_stats_dataframe", return_value=_rows(30)):
        res = sc_mod.get_scoring(sc_mod.ScoringFilters(limit=5))
    assert len(res.opportunities) == 5
    scores = [o.score for o in res.opportunities]
    assert scores == sorted(scores, reverse=True)


def test_scoring_ids_returns_exactly_requested_rows():
    """Modo page-aligned: exactamente las filas pedidas, ignorando min_score/limit."""
    requested = ["L005", "L020", "L029", "L002"]
    with patch.object(sc_mod, "load_stats_dataframe", return_value=_rows(30)):
        res = sc_mod.get_scoring(sc_mod.ScoringFilters(ids=requested, min_score=99, limit=1))
    got = {o.id_externo for o in res.opportunities}
    assert got == set(requested)
    # min_score=99 y limit=1 NO deben recortar en modo ids.
    assert len(res.opportunities) == 4


def test_scoring_ids_normalization_matches_global():
    """El score de una fila es idéntico en top-N y en ids-mode (P10/P90 global)."""
    with patch.object(sc_mod, "load_stats_dataframe", return_value=_rows(30)):
        full = {
            o.id_externo: o.score
            for o in sc_mod.get_scoring(sc_mod.ScoringFilters(limit=500)).opportunities
        }
        one = {
            o.id_externo: o.score
            for o in sc_mod.get_scoring(sc_mod.ScoringFilters(ids=["L005"])).opportunities
        }
    assert one["L005"] == full["L005"]


def test_scoring_ids_unknown_is_empty():
    with patch.object(sc_mod, "load_stats_dataframe", return_value=_rows(10)):
        res = sc_mod.get_scoring(sc_mod.ScoringFilters(ids=["NOPE", "ZZZ"]))
    assert res.opportunities == []


def test_scoring_empty_dataset():
    with patch.object(sc_mod, "load_stats_dataframe", return_value=[]):
        res = sc_mod.get_scoring(sc_mod.ScoringFilters(ids=["L000"]))
    assert res.opportunities == []
    assert res.total_scored == 0
