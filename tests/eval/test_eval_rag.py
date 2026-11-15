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

Baseline medido 2026-07-13 sobre este golden set (FTS puro, el camino que
corría entonces en CI/producción): ``hit_rate@5 = 1.00``, ``MRR = 1.00``. Los
umbrales de abajo son un ratchet con margen bajo ese baseline; si una regresión
de ``search_for_ask`` los rompe, el review debe justificar el cambio, no bajar
el umbral.

Este set ya no discrimina (cualquier motor lo acierta): el ranking por tipo de
consulta lo mide ``test_eval_investigador.py``. Se conserva como red de que el
pipeline retrieval → contexto de ``/ask`` no se rompe.

Nada aquí necesita red ni proveedor LLM: los tests de retrieval llaman al
motor de búsqueda directamente, y el único que toca ``/ask`` sustituye el
generador por un doble. Requieren Postgres (fixture ``tmp_db``), que es lo
que CI levanta para toda la suite.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

_FIXTURE = Path(__file__).parent / "fixtures" / "eval_rag.jsonl"

HIT_RATE_MIN = 0.85
TOP_K = 5

# Ratchet del ranking del camino de producción de ``/ask`` (``search_for_ask``,
# que desde 2026-10-09 responde con el motor de texto del Investigador,
# ``services/investigador/busqueda.py``).
#
# Historia:
# - 2026-07-26, Postgres/tsvector con la tsquery estricta y el LIKE sin orden:
#   hit_rate@5 = 1.000 · MRR ≈ 0.689. El umbral se dejó en 0.65 sin leer el
#   número en CI (el `print` de un test que pasa se lo traga pytest; desde
#   2026-09-19 sale en `GITHUB_STEP_SUMMARY`, ver `_publicar`).
# - 2026-10-17, medido en Postgres 16 local, tres corridas idénticas:
#   producción (/ask) hit_rate@5 = 1.000 · MRR = 1.000, y
#   `PgTsBackend.search_ids` igual (1.000 · 1.000; ese método y los tests que
#   lo medían aquí se retiraron en 2026-11). Basta casar alguno de los
#   términos y el orden pesa los raros (`db/repositories/investigador.py`): el
#   documento esperado sale primero en las 15 preguntas.
#
# El umbral es el valor medido menos un margen de una pregunta: si una de las
# 15 baja del primer puesto al segundo, el MRR queda en 0.967 y pasa. Dos, o
# una que caiga más abajo, ya son una regresión de ranking que hay que mirar,
# no un umbral que bajar.
MRR_MIN = 0.95

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


def _publicar(texto: str) -> None:
    """Imprime ``texto`` y, en GitHub Actions, lo añade al resumen del job.

    El ``print`` solo no llega a ningún sitio en CI: pytest captura la salida
    de los tests que pasan. ``GITHUB_STEP_SUMMARY`` es un fichero que Actions
    pinta en la página de la corrida; fuera de Actions no existe y esto se
    queda en el ``print``. Un fallo al escribirlo no puede tumbar el eval.
    """
    print(texto)
    destino = os.environ.get("GITHUB_STEP_SUMMARY")
    if not destino:
        return
    try:
        with open(destino, "a", encoding="utf-8") as resumen:
            resumen.write(f"```\n{texto.strip()}\n```\n")
    except OSError:
        pass


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
    """Camino que sirve ``/ask`` hoy: ``search_for_ask`` (la búsqueda del Investigador)."""
    from services.licitaciones import search_for_ask

    return [d["id_externo"] for d in search_for_ask(question, TOP_K)]


def test_publicar_llega_al_resumen_del_job(tmp_path, monkeypatch):
    """Sin esto, el MRR que el ratchet necesita leer se imprimía y se perdía."""
    resumen = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(resumen))
    _publicar("\neval_rag: MRR=0.700")
    assert "eval_rag: MRR=0.700" in resumen.read_text(encoding="utf-8")


def test_publicar_fuera_de_actions_solo_imprime(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    _publicar("eval_rag: MRR=0.700")
    assert "MRR=0.700" in capsys.readouterr().out


def test_retrieval_hit_rate_and_mrr_meet_ratchet(tmp_db):
    """Métrica principal del eval: hit-rate@k y MRR sobre el golden set."""
    entries = _load_golden_set()
    assert len(entries) >= 15, "el golden set solo puede crecer"
    _seed(entries)

    hit_rate, mrr, misses = _measure(entries, _retrieve_production)
    hits = round(hit_rate * len(entries))

    _publicar(f"\neval_rag: hit_rate@{TOP_K}={hit_rate:.3f} MRR={mrr:.3f} ({hits}/{len(entries)})")
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
    from tests.claves import clave_de_prueba

    entries = _load_golden_set()
    _seed(entries)

    key = clave_de_prueba("eval-rag-key", scopes="ask:read")
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
