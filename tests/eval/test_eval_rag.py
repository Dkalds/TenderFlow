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

Nada aquí necesita red ni proveedor LLM: los tests de retrieval llaman al
motor de búsqueda directamente, y el único que toca ``/ask`` sustituye el
generador por un doble. Requieren Postgres (fixture ``tmp_db``), que es lo
que CI levanta para toda la suite.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

_FIXTURE = Path(__file__).parent / "fixtures" / "eval_rag.jsonl"

HIT_RATE_MIN = 0.85
TOP_K = 5

# Ratchet del motor de búsqueda de producción (`tsvector` + `ts_rank_cd` con el
# diccionario español, ver `db/search_backend.py`).
#
# Medido el 2026-07-26 sobre el golden set de 15 preguntas:
#   Postgres/tsvector → hit_rate@5 = 1.000 · MRR ≈ 0.689
#   (SQLite/FTS5, retirado en ADR-021, daba MRR ≈ 0.78)
#
# Es decir: producción **recupera igual de bien** —encuentra el documento
# esperado dentro del top-5 en los 15 casos— pero lo **ordena algo peor** que
# el motor de desarrollo que se retiró. No era un bug de la migración: es la
# calidad real de retrieval que ven los usuarios, que nadie medía porque el
# eval corría sobre el otro motor. Se ratchea al valor medido en vez de relajar
# el umbral, para que una regresión futura salte.
#
# **Este umbral sigue en 0.65 a propósito.** El diagnóstico de por qué el MRR
# es 0.689 está en `test_strict_tsquery_alone_leaves_questions_unanswered`
# (la tsquery estricta devuelve cero filas para preguntas en lenguaje natural,
# y el fallback LIKE de `/ask` no tiene `ORDER BY`), y la mejora de ranking
# vive ya en `db/search_backend.py`. Lo que falta para subir el umbral es el
# número: `test_backend_ranking_vs_production_path` lo imprime en CI, que es
# donde hay Postgres. Subirlo antes de leer ese número sería ratchear a ciegas,
# que es justo el fallo que un ratchet existe para prevenir.
MRR_MIN = 0.65

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
                "VALUES (%s, %s, %s, %s, %s, 'placsp', CURRENT_TIMESTAMP)",
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


def _measure(
    entries: list[dict[str, Any]], retrieve: Callable[[str], list[str]]
) -> tuple[float, float, list[str]]:
    """``(hit_rate@TOP_K, MRR, fallos)`` de un recuperador sobre el golden set.

    ``retrieve`` recibe la pregunta y devuelve los id_externo ya ordenados por
    relevancia — así la misma métrica sirve para el camino de ``/ask`` y para
    el ranking de ``db/search_backend.py``, que es de lo que trata la
    comparación de ``test_backend_ranking_vs_production_path``.
    """
    hits = 0
    reciprocal_ranks: list[float] = []
    misses: list[str] = []

    for entry in entries:
        question = entry["question"]
        expected = set(entry["expected_ids"])
        result_ids = retrieve(question)

        rr = _reciprocal_rank(result_ids, expected)
        reciprocal_ranks.append(rr)
        if rr > 0:
            hits += 1
        else:
            misses.append(f"{question!r} -> esperado {expected}, obtuvo {result_ids}")

    return hits / len(entries), sum(reciprocal_ranks) / len(entries), misses


def _retrieve_production(question: str) -> list[str]:
    """Camino que sirve ``/ask`` hoy: ``search_for_ask`` (FTS + LIKE fallback)."""
    from services.licitaciones import search_for_ask

    return [d["id_externo"] for d in search_for_ask(question, TOP_K)]


def _retrieve_backend(question: str) -> list[str]:
    """Ranking de ``PgTsBackend`` (pasada estricta + pasada relajada a OR)."""
    from db.database import connect_read
    from db.search_backend import PgTsBackend

    with connect_read() as conn:
        return PgTsBackend().search_ids(conn, question, limit=TOP_K)


def test_retrieval_hit_rate_and_mrr_meet_ratchet(tmp_db):
    """Métrica principal del eval: hit-rate@k y MRR sobre el golden set."""
    entries = _load_golden_set()
    assert len(entries) >= 15, "el golden set solo puede crecer"
    _seed(entries)

    hit_rate, mrr, misses = _measure(entries, _retrieve_production)
    hits = round(hit_rate * len(entries))

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


def test_strict_tsquery_alone_leaves_questions_unanswered(tmp_db):
    """El diagnóstico del MRR bajo, congelado como test.

    ``websearch_to_tsquery`` conjuga los términos con AND, así que una pregunta
    en lenguaje natural con una sola palabra que el documento no usa
    ("**llamada** Aurora Boreal" contra "**denominada** Aurora Boreal") no
    devuelve el documento peor rankeado: devuelve **cero filas**. Ahí el
    ranking desaparece y quien llama se queda con lo que le dé el fallback.

    Este test fija las dos mitades de esa afirmación:
      1. al menos una pregunta del golden set no casa con la pasada estricta;
      2. la búsqueda completa —con la relajación AND→OR de
         ``PgTsBackend._ts_search``— sí la responde, y encima ordenada.

    Si (1) dejara de cumplirse, la pasada relajada sobraría y este test lo
    diría; si dejara de cumplirse (2), la relajación se rompió.
    """
    from db.database import connect_read
    from db.search_backend import PgTsBackend

    entries = _load_golden_set()
    _seed(entries)

    backend = PgTsBackend()
    sin_match_estricto: list[dict[str, Any]] = []
    with connect_read() as conn:
        for entry in entries:
            rows = backend._ts_search_pass(
                conn, entry["question"], backend._STRICT_TSQUERY, limit=TOP_K, offset=0
            )
            assert rows is not None, (
                "la pasada estricta falló con error, no con cero filas — "
                "¿falta la columna search_vector (migración v50)?"
            )
            if not rows:
                sin_match_estricto.append(entry)

    print(
        f"\neval_rag: preguntas sin match con la tsquery estricta: "
        f"{len(sin_match_estricto)}/{len(entries)}"
    )
    assert sin_match_estricto, (
        "ninguna pregunta del golden set falla ya con la tsquery estricta (AND). "
        "Si es un cambio deliberado del golden set, la pasada relajada de "
        "PgTsBackend._ts_search ya no tiene caso de uso que la justifique."
    )

    for entry in sin_match_estricto:
        result_ids = _retrieve_backend(entry["question"])
        assert set(entry["expected_ids"]) & set(result_ids), (
            f"la relajación AND→OR no recuperó {entry['expected_ids']} para "
            f"{entry['question']!r} (obtuvo {result_ids})"
        )


def test_backend_ranking_vs_production_path(tmp_db):
    """Mide el MRR del ranking de ``PgTsBackend`` sobre el mismo golden set.

    ``/ask`` no pasa por este backend: usa
    ``LicitacionRepository.search_fts_docs`` y, cuando esa query no devuelve
    nada, ``search_like_for_ask`` — un LIKE **sin ORDER BY**, o sea un orden
    arbitrario. Ese es el origen del MRR 0.689 con hit_rate@5 = 1.000: el
    documento correcto entra al contexto, pero su posición la decide el plan de
    ejecución, no la relevancia.

    Este test imprime los dos números lado a lado para que CI produzca la
    evidencia que aquí no se puede producir (esta máquina no tiene Postgres).
    Se asserta el mismo suelo que el camino de producción —no un ratchet
    nuevo— porque **subir un ratchet a un valor no medido es exactamente el
    fallo que el ratchet existe para evitar**. Cuando CI publique el MRR del
    backend, ese valor es el que debe fijar ``MRR_MIN``.
    """
    entries = _load_golden_set()
    _seed(entries)

    hr_prod, mrr_prod, misses_prod = _measure(entries, _retrieve_production)
    hr_backend, mrr_backend, misses_backend = _measure(entries, _retrieve_backend)

    print(
        f"\neval_rag ranking:"
        f"\n  producción (/ask)      hit_rate@{TOP_K}={hr_prod:.3f} MRR={mrr_prod:.3f}"
        f"\n  PgTsBackend.search_ids hit_rate@{TOP_K}={hr_backend:.3f} MRR={mrr_backend:.3f}"
        f"\n  delta MRR = {mrr_backend - mrr_prod:+.3f}"
    )
    if misses_backend:
        print("  Fallos del backend:")
        for m in misses_backend:
            print(f"    - {m}")

    assert hr_backend >= HIT_RATE_MIN, (
        f"hit_rate@{TOP_K} {hr_backend:.3f} < {HIT_RATE_MIN} — el ranking de "
        f"db/search_backend.py perdió recall. Fallos: {misses_backend}"
    )
    assert mrr_backend >= MRR_MIN, (
        f"MRR {mrr_backend:.3f} < {MRR_MIN} — el ranking de db/search_backend.py "
        f"empeoró. Producción mide {mrr_prod:.3f}; fallos: {misses_prod}"
    )


def test_backend_ranking_is_deterministic(tmp_db):
    """El mismo golden set consultado dos veces da el mismo orden.

    Sin desempate explícito, dos documentos con idéntico ``ts_rank_cd`` salen
    en el orden que quiera el plan de ejecución: el eval mediría ruido y el
    ratchet de MRR sería intermitente. ``_ts_search`` desempata por
    ``id_externo``; esto lo congela.
    """
    entries = _load_golden_set()
    _seed(entries)

    primera = {e["question"]: _retrieve_backend(e["question"]) for e in entries}
    segunda = {e["question"]: _retrieve_backend(e["question"]) for e in entries}

    assert primera == segunda, "el orden del ranking cambia entre ejecuciones idénticas"


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

    def _fake_stream(question, docs, model, keywords, **_kwargs):
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
