"""Eval manual de generación RAG contra un LLM real (plan Pliegos+RAG, F10).

Complementa ``tests/eval/test_eval_rag.py`` (recuperación, determinista, en
CI): este script llama al LLM configurado de verdad para inspeccionar la
CALIDAD de la respuesta generada — no determinista, cuesta dinero por
ejecución, por eso vive fuera del gate de CI (RFC llm-dependencia-gestionada
§3: "no se mete un eval de generación LLM en el gate de CI"). Imprime cada
pregunta, los documentos recuperados y la respuesta generada para revisión
humana.

Mide además, sin intervención humana, **la tasa de citas válidas en modo
licitación** (C5.3 / D29): el objetivo del plan es ≥ 90 % de respuestas con al
menos una fuente que exista en el contexto enviado. La validación la hace el
mismo módulo que la ruta (``services/rag/citas``), así que lo que se mide aquí
es exactamente lo que el usuario recibe. La *calidad* de la respuesta sigue sin
pass/fail automático: eso es revisión humana.

Uso::

    make eval-llm
    # o directamente, con un modelo concreto:
    python scripts/eval_rag_generation.py --model gpt-4o-mini
    # exigiendo el umbral del plan (devuelve 1 si no se alcanza):
    python scripts/eval_rag_generation.py --min-citas 0.9
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
    parser.add_argument(
        "--min-citas",
        type=float,
        default=None,
        help=(
            "Tasa mínima de respuestas con fuente válida en modo licitación "
            "(0-1). Sin este flag solo se informa."
        ),
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

    from services.rag.citas import evento_sources

    con_contexto = 0
    con_fuente = 0
    inventadas = 0

    for i, entry in enumerate(entries, start=1):
        question = entry["question"]
        docs = search_for_ask(question, top_k=5)
        print(f"\n{'=' * 70}\n[{i}/{len(entries)}] {question}")
        print(f"  esperado: {entry['expected_ids']}")
        print(f"  recuperado: {[d['id_externo'] for d in docs]}")
        keywords = [w for w in question.split() if len(w) > 3][:10]
        print("  respuesta:")
        partes: list[str] = []
        try:
            for chunk in stream_llm_response(question, docs, model, keywords):
                partes.append(chunk)
                print(chunk, end="", flush=True)
            print()
        except Exception as e:
            print(f"  [ERROR generando respuesta: {e}]")
            continue

        chunks = [c for d in docs for c in (d.get("chunks") or [])]
        if not chunks:
            # Sin fragmentos de pliego no hay nada que citar: contar esta
            # respuesta en el denominador castigaría al modelo por un hueco del
            # corpus, y la métrica dejaría de medir lo que dice medir.
            print("  [citas: sin fragmentos de pliego en el contexto — fuera de la métrica]")
            continue
        con_contexto += 1
        evento = evento_sources("".join(partes), chunks)
        inventadas += int(evento["descartadas"])
        if not evento["sin_fuentes"]:
            con_fuente += 1
        print(f"  [citas: {len(evento['sources'])} válidas, {evento['descartadas']} inventadas]")

    print(f"\n{'=' * 70}")
    if con_contexto:
        tasa = con_fuente / con_contexto
        print(
            f"Citas válidas (C5.3): {con_fuente}/{con_contexto} respuestas "
            f"= {tasa:.0%}; {inventadas} marcador/es inventado/s. Objetivo del plan: 90 %."
        )
        if args.min_citas is not None and tasa < args.min_citas:
            print(f"FALLO: {tasa:.0%} por debajo del mínimo exigido ({args.min_citas:.0%}).")
            return 1
    else:
        print("Citas válidas (C5.3): sin población — ninguna pregunta trajo pliegos.")

    print(
        "Revisión manual: ¿las respuestas citan correctamente los documentos "
        "recuperados y responden la pregunta con datos reales (no alucinados)?"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
