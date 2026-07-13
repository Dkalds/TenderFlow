"""Eval manual de generación RAG contra un LLM real (plan Pliegos+RAG, F10).

Complementa ``tests/eval/test_eval_rag.py`` (recuperación, determinista, en
CI): este script llama al LLM configurado de verdad para inspeccionar la
CALIDAD de la respuesta generada — no determinista, cuesta dinero por
ejecución, por eso vive fuera del gate de CI (RFC llm-dependencia-gestionada
§3: "no se mete un eval de generación LLM en el gate de CI"). Imprime cada
pregunta, los documentos recuperados y la respuesta generada para revisión
humana; no hay pass/fail automático.

Uso::

    make eval-llm
    # o directamente, con un modelo concreto:
    python scripts/eval_rag_generation.py --model gpt-4o-mini
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE = _REPO_ROOT / "tests" / "eval" / "fixtures" / "eval_rag.jsonl"


def _load_golden_set() -> list[dict]:
    entries = []
    for raw in _FIXTURE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        entries.append(json.loads(line))
    return entries


def _seed_temp_db(entries: list[dict]) -> None:
    from db.database import Licitacion, init_db, upsert_licitaciones

    init_db()
    licitaciones = [
        Licitacion(
            id_externo=entry["licitacion"]["id_externo"],
            titulo=entry["licitacion"]["titulo"],
            descripcion=entry["licitacion"]["descripcion"],
            organo_contratacion=entry["licitacion"]["organo"],
            cpv=entry["licitacion"]["cpv"],
        )
        for entry in entries
    ]
    upsert_licitaciones(licitaciones)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model", default=None, help="Modelo LLM (default: llm.client.DEFAULT_MODEL)"
    )
    parser.add_argument(
        "--limit", type=int, default=5, help="Nº de preguntas del golden set a probar"
    )
    args = parser.parse_args()

    sys.path.insert(0, str(_REPO_ROOT))
    import tempfile

    from config import settings

    settings.DB_PATH = Path(tempfile.mkdtemp()) / "eval_rag_llm.db"

    from llm.client import DEFAULT_MODEL, stream_llm_response
    from services.licitaciones import search_for_ask

    model = args.model or DEFAULT_MODEL
    entries = _load_golden_set()[: args.limit]

    _seed_temp_db(entries)

    for i, entry in enumerate(entries, start=1):
        question = entry["question"]
        docs = search_for_ask(question, top_k=5)
        print(f"\n{'=' * 70}\n[{i}/{len(entries)}] {question}")
        print(f"  esperado: {entry['expected_ids']}")
        print(f"  recuperado: {[d['id_externo'] for d in docs]}")
        keywords = [w for w in question.split() if len(w) > 3][:10]
        print("  respuesta:")
        try:
            for chunk in stream_llm_response(question, docs, model, keywords):
                print(chunk, end="", flush=True)
            print()
        except Exception as e:
            print(f"  [ERROR generando respuesta: {e}]")

    print(
        f"\n{'=' * 70}\nRevisión manual: ¿las respuestas citan correctamente los documentos "
        "recuperados y responden la pregunta con datos reales (no alucinados)?"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
