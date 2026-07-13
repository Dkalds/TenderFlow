"""Eval determinista de retrieval para RAG (plan Pliegos+RAG, F10; RFC LLM parte 3).

Sin LLM real: mide **recuperación** (¿el documento correcto entra al
contexto?), no calidad de generación — eso es lo que hace este eval
determinista y apto para el gate de CI (RFC llm-dependencia-gestionada:
"eval de recuperación... que falla si se rompe el contexto recuperado").

Golden set (``fixtures/eval_rag.jsonl``, 15 preguntas): cada licitación
sembrada lleva una palabra clave distintiva inventada (nombre en clave del
proyecto — "Fénix", "Nébula", "Escudo Cuántico"...) tanto en el título como
en la pregunta, de forma que el ranking BM25/LIKE la identifique sin
ambigüedad incluso con licitaciones de "ruido" (términos genéricos SAP/ERP
que se solapan a propósito) sembradas junto a ellas.

Baseline medido 2026-07-13 sobre este golden set (FTS puro, flag
``RAG_HYBRID_ENABLED`` en su default False — el camino que realmente corre
en CI/producción hoy): ``hit_rate@5 = 1.00``, ``MRR = 1.00``. Los umbrales de
abajo son un ratchet con margen bajo ese baseline; si una regresión de
``search_for_ask``/``escape_fts5``/``search_like_for_ask`` los rompe, el
review debe justificar el cambio, no bajar el umbral.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

_FIXTURE = Path(__file__).parent / "fixtures" / "eval_rag.jsonl"

HIT_RATE_MIN = 0.85
MRR_MIN = 0.75
TOP_K = 5

# Licitaciones "ruido": vocabulario genérico que se solapa con el golden set
# (SAP, ERP, cloud, IA...) para que el eval no sea trivial — sin ruido,
# cualquier heurística de retrieval acertaría por defecto al haber una sola
# licitación en la BD relevante por pregunta.
_NOISE_LICITACIONES = [
    {
        "id_externo": "NOISE-1",
        "titulo": "Soporte SAP genérico para organismo público",
        "descripcion": "Servicio de soporte y mantenimiento SAP estándar sin proyecto asociado.",
        "cpv": "72267100",
        "organo": "Organismo genérico A",
    },
    {
        "id_externo": "NOISE-2",
        "titulo": "Consultoría de transformación digital genérica",
        "descripcion": "Consultoría de transformación digital sin denominación de proyecto específica.",
        "cpv": "72224000",
        "organo": "Organismo genérico B",
    },
    {
        "id_externo": "NOISE-3",
        "titulo": "Licencias Microsoft 365 para oficinas centrales",
        "descripcion": "Renovación estándar de licencias Microsoft 365 sin proyecto asociado.",
        "cpv": "48219000",
        "organo": "Organismo genérico C",
    },
    {
        "id_externo": "NOISE-4",
        "titulo": "Servicios de inteligencia artificial genéricos",
        "descripcion": "Consultoría de inteligencia artificial de propósito general.",
        "cpv": "73300000",
        "organo": "Organismo genérico D",
    },
]


def _load_golden_set() -> list[dict[str, Any]]:
    entries = []
    for raw in _FIXTURE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        entries.append(json.loads(line))
    return entries


def _seed(entries: list[dict[str, Any]]) -> None:
    from db.database import connect

    licitaciones = [e["licitacion"] for e in entries] + _NOISE_LICITACIONES
    with connect() as c:
        for lic in licitaciones:
            c.execute(
                "INSERT INTO licitaciones "
                "(id_externo, titulo, descripcion, organo_contratacion, cpv, "
                " fuente, fecha_extraccion) "
                "VALUES (?, ?, ?, ?, ?, 'placsp', datetime('now'))",
                (
                    lic["id_externo"],
                    lic["titulo"],
                    lic["descripcion"],
                    lic["organo"],
                    lic["cpv"],
                ),
            )


def _reciprocal_rank(result_ids: list[str], expected_ids: set[str]) -> float:
    for i, rid in enumerate(result_ids, start=1):
        if rid in expected_ids:
            return 1.0 / i
    return 0.0


def test_retrieval_hit_rate_and_mrr_meet_ratchet(tmp_db):
    """Métrica principal del eval: hit-rate@k y MRR sobre el golden set."""
    from services.licitaciones import search_for_ask

    entries = _load_golden_set()
    assert len(entries) >= 15, "el golden set solo puede crecer"
    _seed(entries)

    hits = 0
    reciprocal_ranks = []
    misses: list[str] = []

    for entry in entries:
        question = entry["question"]
        expected = set(entry["expected_ids"])
        docs = search_for_ask(question, TOP_K)
        result_ids = [d["id_externo"] for d in docs]

        rr = _reciprocal_rank(result_ids, expected)
        reciprocal_ranks.append(rr)
        if rr > 0:
            hits += 1
        else:
            misses.append(f"{question!r} -> esperado {expected}, obtuvo {result_ids}")

    hit_rate = hits / len(entries)
    mrr = sum(reciprocal_ranks) / len(entries)

    print(f"\neval_rag: hit_rate@{TOP_K}={hit_rate:.3f} MRR={mrr:.3f} ({hits}/{len(entries)})")
    if misses:
        print("  Fallos:")
        for m in misses:
            print(f"    - {m}")

    assert hit_rate >= HIT_RATE_MIN, (
        f"hit_rate@{TOP_K} {hit_rate:.3f} < {HIT_RATE_MIN} — el contexto recuperado "
        f"para /ask se rompió. Fallos: {misses}"
    )
    assert mrr >= MRR_MIN, f"MRR {mrr:.3f} < {MRR_MIN} — el ranking de retrieval empeoró."


def test_retrieval_respects_ccaa_filter_without_losing_target(tmp_db):
    """Regresión dirigida: un filtro que no aplica a la licitación esperada
    no debe hacerla desaparecer de los resultados."""
    from services.licitaciones import search_for_ask

    entries = _load_golden_set()
    _seed(entries)

    entry = next(e for e in entries if e["expected_ids"] == ["EVAL-001"])
    docs = search_for_ask(entry["question"], TOP_K)
    assert any(d["id_externo"] == "EVAL-001" for d in docs)


def test_ask_endpoint_context_includes_expected_licitacion(tmp_db):
    """Capa de integración con generador mockeado (sin LLM real): confirma que
    el contexto que llega al generador de /ask incluye la licitación correcta
    -- no evalúa calidad de generación, solo que el pipeline retrieval->contexto
    no se rompe end-to-end."""
    from fastapi.testclient import TestClient

    from api.app import app
    from api.auth import create_api_key

    entries = _load_golden_set()
    _seed(entries)

    key = create_api_key("eval-rag-key", scopes="ask:read")
    client = TestClient(app, raise_server_exceptions=False)
    client.headers.update({"X-API-Key": key})

    captured_docs: list[list[dict[str, Any]]] = []

    def _fake_stream(question, docs, model, keywords):
        captured_docs.append(docs)
        yield "respuesta simulada"

    sample = entries[:5]  # subconjunto — el test de arriba ya cubre el set completo
    for entry in sample:
        with patch("llm.client.stream_llm_response", _fake_stream):
            resp = client.post("/api/v1/ask", json={"question": entry["question"]})
        assert resp.status_code == 200

    assert len(captured_docs) == len(sample)
    for entry, docs in zip(sample, captured_docs, strict=True):
        result_ids = {d["id_externo"] for d in docs}
        assert set(entry["expected_ids"]) & result_ids, (
            f"contexto de /ask para {entry['question']!r} no incluyó "
            f"{entry['expected_ids']} (obtuvo {result_ids})"
        )
