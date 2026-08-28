"""Gate de calidad del dedupe cross-fuente sobre el golden set etiquetado a mano.

RFC 2026-06-30 (validación dedupe + linaje): el guardrail existente
(``test_dedup_guardrail.py``) verifica que las queries *filtren* duplicados;
este test verifica que el *matching acierte*. Corre ``detect_duplicates`` sobre
``tests/fixtures/dedupe_golden.jsonl`` (pares cross-fuente con etiqueta humana
``duplicate``/``distinct``) y mide:

- **precision (confirmed)** — GATE. Un falso positivo *confirmed* borra una
  licitación real del análisis de competencia: es el error caro.
- **recall (cualquier marca, confirmed+pending)** — solo informativo. Los
  falsos negativos conocidos (siglas vs nombre completo, formatos de
  expediente divergentes) están etiquetados en el fixture y documentan los
  límites de la clave débil actual.

Baseline medido 2026-07-12 sobre el golden set inicial (58 pares):

    precision_confirmed = 0.933   (28 TP / 2 FP conocidos)
    recall_any          = 0.857   (36 de 42 duplicados marcados)

``PRECISION_MIN`` es un **ratchet**: baseline − margen (0.90). Si un cambio de
normalización/matching lo baja, CI falla — se revisa el cambio, no el umbral.
Solo puede subir; bajarlo requiere justificación explícita en review (RFC).
"""

from __future__ import annotations

import json
from pathlib import Path

_FIXTURE = Path(__file__).parent / "fixtures" / "dedupe_golden.jsonl"

PRECISION_MIN = 0.90
# Sanity: si el harness se rompe (detect_duplicates no marca nada) la precision
# sería 0/0 — exigir un mínimo de confirmados hace que el fallo sea ruidoso.
MIN_CONFIRMED_EXPECTED = 20


def _load_pairs() -> list[dict]:
    pairs = []
    for raw in _FIXTURE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pairs.append(json.loads(line))
    return pairs


def _insert_lic(c, side: dict) -> None:
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, "
        " fecha_publicacion, fuente, fecha_extraccion) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            side["id"],
            f"Contrato {side['id']}",
            side.get("organo"),
            side.get("cpv"),
            side.get("fecha_pub"),
            side["fuente"],
            side.get("extraccion"),
        ),
    )


def test_dedupe_golden_precision_gate(tmp_db):
    from db.database import connect
    from services.dedupe import detect_duplicates

    pairs = _load_pairs()
    assert len(pairs) >= 50, "el golden set solo puede crecer"

    with connect() as c:
        for pair in pairs:
            _insert_lic(c, pair["a"])
            _insert_lic(c, pair["b"])

    for fuente in sorted({p["b"]["fuente"] for p in pairs}):
        detect_duplicates(fuente=fuente)

    with connect() as c:
        marks = {
            (r[0], r[1]): r[2]
            for r in c.execute(
                "SELECT licitacion_id, canonical_id, status FROM licitaciones_duplicados"
            ).fetchall()
        }

    # Integridad del fixture: toda marca debe corresponder a un par del golden
    # set — una marca cruzada delataría colisión de expedientes entre pares.
    golden_ids = {frozenset((p["a"]["id"], p["b"]["id"])) for p in pairs}
    for lic, canon in marks:
        assert frozenset((lic, canon)) in golden_ids, (
            f"marca fuera del golden set: {lic} ↔ {canon} — "
            "colisión de expedientes entre pares del fixture"
        )

    def _status(pair: dict) -> str | None:
        a, b = pair["a"]["id"], pair["b"]["id"]
        return marks.get((a, b)) or marks.get((b, a))

    tp_confirmed = fp_confirmed = 0
    dup_total = dup_matched_any = 0
    fp_cases: list[str] = []
    fn_cases: list[str] = []
    for pair in pairs:
        status = _status(pair)
        if pair["label"] == "duplicate":
            dup_total += 1
            if status is not None:
                dup_matched_any += 1
            else:
                fn_cases.append(pair.get("case", "?"))
            if status == "confirmed":
                tp_confirmed += 1
        else:
            if status == "confirmed":
                fp_confirmed += 1
                fp_cases.append(pair.get("case", "?"))

    assert tp_confirmed >= MIN_CONFIRMED_EXPECTED, (
        f"solo {tp_confirmed} confirmados — ¿harness roto o golden set recortado%s"
    )

    precision = tp_confirmed / (tp_confirmed + fp_confirmed)
    recall_any = dup_matched_any / dup_total if dup_total else 0.0
    print(
        f"\ndedupe golden: precision_confirmed={precision:.3f} "
        f"(TP={tp_confirmed} FP={fp_confirmed}) recall_any={recall_any:.3f} "
        f"({dup_matched_any}/{dup_total})"
    )
    if fp_cases:
        print(f"  FP confirmados (conocidos): {fp_cases}")
    if fn_cases:
        print(f"  FN (límites conocidos de la clave débil): {fn_cases}")

    assert precision >= PRECISION_MIN, (
        f"precision del dedupe {precision:.3f} < {PRECISION_MIN} — un FP confirmado "
        f"borra licitaciones reales del análisis. FP nuevos: {fp_cases}. "
        "Revisá el cambio de matching/normalización antes que el umbral (RFC dedupe)."
    )


def _metric_value(name: str, labels: dict[str, str]) -> float | None:
    """Lee una métrica del REGISTRY; None si prometheus_client no está instalado."""
    try:
        from prometheus_client import REGISTRY
    except ImportError:
        return None
    val = REGISTRY.get_sample_value(name, labels)
    return float(val) if val is not None else 0.0


def test_detect_duplicates_instrumenta_metricas(tmp_db):
    """RFC dedupe/linaje: dedupe_marked_total{source_pair} y dedupe_match_rate."""
    import pytest

    from db.database import connect
    from services.dedupe import detect_duplicates

    before = _metric_value(
        "dedupe_marked_total", {"source_pair": "placsp|pscp", "status": "confirmed"}
    )
    if before is None:
        pytest.skip("prometheus_client no instalado — métricas no-op")

    with connect() as c:
        _insert_lic(
            c,
            {
                "id": "MET-2026-1",
                "fuente": "placsp",
                "organo": "Organo Metricas",
                "cpv": "72000000",
                "fecha_pub": "2026-05-01",
                "extraccion": "2026-05-02T00:00:00",
            },
        )
        _insert_lic(
            c,
            {
                "id": "pscp:MET-2026-1",
                "fuente": "pscp",
                "organo": "Organo Metricas",
                "cpv": "72000000",
                "fecha_pub": "2026-05-01",
                "extraccion": "2026-05-03T00:00:00",
            },
        )
        _insert_lic(
            c,
            {
                "id": "pscp:MET-2026-solo",
                "fuente": "pscp",
                "organo": "Organo Sin Par",
                "cpv": "48000000",
                "fecha_pub": "2026-05-01",
                "extraccion": "2026-05-03T00:00:00",
            },
        )

    result = detect_duplicates(fuente="pscp")
    assert result.confirmados == 1 and result.evaluadas == 2

    after = _metric_value(
        "dedupe_marked_total", {"source_pair": "placsp|pscp", "status": "confirmed"}
    )
    assert after is not None and after - before == 1.0

    rate = _metric_value("dedupe_match_rate", {"fuente": "pscp"})
    assert rate == 0.5  # 1 marcada de 2 evaluadas en la última pasada


def test_dedupe_roto_en_la_ingesta_deja_senal_y_no_solo_un_log():
    """El ``except`` fail-open de ``_post_ingestion`` incrementa un contador.

    Sin él, un ``detect_duplicates`` que reventara en todas las pasadas —lo que
    hacía el índice de candidatas sin acotar, por memoria— dejaba el run marcado
    como exitoso y no había ninguna serie temporal donde se viera. El fail-open
    se conserva: la ingesta no puede caerse por el dedupe.
    """
    from unittest.mock import patch

    import pytest

    from scraper.connectors.base import _post_ingestion

    before = _metric_value("dedupe_run_failed_total", {"fuente": "pscp"})
    if before is None:
        pytest.skip("prometheus_client no instalado — métricas no-op")

    with (
        patch("services.entity_resolution.resolve_all_unlinked"),
        patch("services.dedupe.detect_duplicates", side_effect=RuntimeError("índice roto")),
        patch("services.contract_events.derive_new_events"),
        patch("shared.cache_signal.signal_cache_invalidation"),
    ):
        _post_ingestion("pscp")  # no propaga: el fail-open sigue en pie

    after = _metric_value("dedupe_run_failed_total", {"fuente": "pscp"})
    assert after is not None and after - before == 1.0
