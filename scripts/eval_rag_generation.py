"""Eval manual de generación RAG contra un LLM real (plan Pliegos+RAG, F10).

Complementa ``tests/eval/test_eval_rag.py`` (recuperación, determinista, en
CI): este script llama al LLM configurado de verdad para inspeccionar la
CALIDAD de la respuesta generada — no determinista, cuesta dinero por
ejecución, por eso vive fuera del gate de CI (RFC llm-dependencia-gestionada
§3: "no se mete un eval de generación LLM en el gate de CI"). Imprime cada
pregunta, los documentos recuperados y la respuesta generada para revisión
humana.

**No usa base de datos.** La recuperación se emula sobre el propio golden set
(``tests/eval/fixtures/eval_rag.jsonl``): cada pregunta recibe las licitaciones
del golden set con más palabras en común, con la forma que devuelve
``search_for_ask``. La recuperación real ya la mide ``test_eval_rag.py``; aquí
se prueban el modelo, el prompt y la validación de citas, que son los de
producción.

Hasta 2026-09 el script sembraba el golden set con ``upsert_licitaciones`` en
lo que dijera ``DATABASE_URL``: el ``settings.DB_PATH`` temporal que lo aislaba
era de la época SQLite y dejó de aislar nada con ADR-021. Desde el checkout
principal, cuyo ``.env`` apunta a producción, eso escribía las licitaciones
falsas ``EVAL-0xx`` en producción. Ahora el proceso arranca además con
``DATABASE_URL`` vacía, para que una consulta que alguien reintroduzca falle en
vez de llegar a una base real (``tests/test_unit_eval_rag_generation.py``).

Cuenta sin intervención humana **si cada respuesta cita el expediente
esperado** como pide el prompt general, con el id entre corchetes copiado del
contexto. También cuenta los ids entre corchetes que no estaban en el contexto
enviado (el ``[EXP-2024-001]`` del ejemplo del prompt, o uno inventado) y las
respuestas vacías. Es lo que se contó a mano en el eval del cambio de modelo
del 2026-09-24.

Mide además **la tasa de citas válidas** de pliego (C5.3 / D29): el objetivo
del plan es ≥ 90 % de respuestas en modo licitación con al menos una fuente que
exista en el contexto enviado. La validación la hace el mismo módulo que la
ruta (``services/rag/citas``). Solo cuentan las respuestas cuyo contexto trae
fragmentos de pliego, y el golden set no los tiene: hoy la métrica sale «sin
población» y ``--min-citas`` no puede fallar. La *calidad* de la respuesta
sigue sin pass/fail automático: eso es revisión humana.

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
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE = _REPO_ROOT / "tests" / "eval" / "fixtures" / "eval_rag.jsonl"

#: Documentos de contexto por pregunta: el ``top_k`` por defecto de ``/ask``.
_TOP_K = 5

#: Un id de expediente citado como pide el prompt general: entre corchetes y
#: copiado tal cual del contexto (``[EXP-2024-001]``, ``llm/prompts.py``). Se
#: exige un dígito para no contar un ``[Nota]``, y se excluyen espacios y «:»
#: para no confundirlo con los marcadores de pliego ``[doc:N p.M]``.
_ID_ENTRE_CORCHETES = re.compile(r"\[(?=[^\[\]\s:]*\d)([^\[\]\s:]{3,40})\]")


def _load_golden_set() -> list[dict[str, Any]]:
    entries = []
    for raw in _FIXTURE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        entries.append(json.loads(line))
    return entries


def _sin_bd() -> None:
    """Deja el proceso sin base de datos: cualquier conexión falla al abrirse.

    ``db.connection._database_url`` mira primero la variable de entorno y luego
    ``settings.DATABASE_URL``, que ``config.settings`` carga del ``.env`` del
    directorio de trabajo (en el checkout principal, producción). Se vacían
    las dos: la variable por si el shell la exporta, y el atributo por si
    ``config`` ya estaba importado cuando se llega aquí.
    """
    os.environ["DATABASE_URL"] = ""

    from pydantic import SecretStr

    from config import settings

    settings.DATABASE_URL = SecretStr("")


def _palabras(texto: str) -> set[str]:
    """Palabras de más de tres letras, en minúsculas y sin tildes."""
    plano = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    return {p for p in re.findall(r"\w+", plano) if len(p) > 3}


def _corpus(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Las licitaciones del golden set, con las claves que usa el prompt."""
    return [
        {
            "id_externo": e["licitacion"]["id_externo"],
            "titulo": e["licitacion"]["titulo"],
            "descripcion": e["licitacion"]["descripcion"],
            "organo_contratacion": e["licitacion"]["organo"],
            "cpv": e["licitacion"]["cpv"],
        }
        for e in entries
    ]


def _recuperar(pregunta: str, corpus: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    """Sustituto de ``search_for_ask``: las ``top_k`` con más palabras en común.

    No imita el ranking de producción: busca que el modelo reciba la licitación
    correcta junto a otras que se le parecen, como en ``/ask``. Las que no
    comparten ninguna palabra quedan fuera, igual que en la búsqueda real, y el
    empate se resuelve por ``id_externo`` para que dos ejecuciones manden el
    mismo contexto.
    """
    consulta = _palabras(pregunta)
    puntuados: list[tuple[int, dict[str, Any]]] = []
    for doc in corpus:
        texto = f"{doc['titulo']} {doc['descripcion']} {doc['organo_contratacion']}"
        solape = len(consulta & _palabras(texto))
        if solape:
            puntuados.append((solape, doc))
    puntuados.sort(key=lambda par: (-par[0], par[1]["id_externo"]))
    return [doc for _, doc in puntuados[:top_k]]


def _citas_de_expediente(texto: str, docs: list[dict[str, Any]]) -> tuple[set[str], list[str]]:
    """``(citados, ajenos)`` de una respuesta en modo general.

    ``citados``: los expedientes del contexto que la respuesta cita entre
    corchetes. ``ajenos``: los ids entre corchetes que no estaban en el
    contexto, sea el ejemplo del prompt copiado o un expediente inventado. Un id
    sin corchetes no cuenta como cita, porque el prompt pide el corchete.
    """
    del_contexto = {str(d["id_externo"]) for d in docs}
    ids = set(_ID_ENTRE_CORCHETES.findall(texto))
    return ids & del_contexto, sorted(ids - del_contexto)


def main(argv: list[str] | None = None) -> int:
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
    args = parser.parse_args(argv)

    sys.path.insert(0, str(_REPO_ROOT))
    _sin_bd()

    from llm.client import DEFAULT_MODEL, stream_llm_response
    from services.rag.citas import evento_sources

    model = args.model or DEFAULT_MODEL
    golden = _load_golden_set()
    # El corpus es el golden set entero aunque `--limit` recorte las preguntas:
    # con solo las licitaciones preguntadas, el contexto se quedaría sin
    # distractores.
    corpus = _corpus(golden)
    entries = golden[: args.limit]

    con_esperado = 0
    ids_ajenos = 0
    vacias = 0
    errores = 0
    con_contexto = 0
    con_fuente = 0
    inventadas = 0

    for i, entry in enumerate(entries, start=1):
        question = entry["question"]
        docs = _recuperar(question, corpus, _TOP_K)
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
            errores += 1
            continue

        texto = "".join(partes)
        if not texto.strip():
            vacias += 1
        citados, ajenos = _citas_de_expediente(texto, docs)
        if citados & set(entry["expected_ids"]):
            con_esperado += 1
        ids_ajenos += len(ajenos)
        print(f"  [expedientes: citados {sorted(citados)}, ajenos al contexto {ajenos}]")

        chunks = [c for d in docs for c in (d.get("chunks") or [])]
        if not chunks:
            # Sin fragmentos de pliego no hay nada que citar: contar esta
            # respuesta en el denominador castigaría al modelo por un hueco del
            # corpus, y la métrica dejaría de medir lo que dice medir.
            print("  [citas: sin fragmentos de pliego en el contexto — fuera de la métrica]")
            continue
        con_contexto += 1
        evento = evento_sources(texto, chunks)
        inventadas += int(evento["descartadas"])
        if not evento["sin_fuentes"]:
            con_fuente += 1
        print(f"  [citas: {len(evento['sources'])} válidas, {evento['descartadas']} inventadas]")

    print(f"\n{'=' * 70}")
    con_error = f"; {errores} pregunta/s con error" if errores else ""
    print(
        f"Expedientes: el esperado se cita en {con_esperado}/{len(entries)} preguntas; "
        f"{ids_ajenos} id/s ajeno/s al contexto; {vacias} respuesta/s vacía/s{con_error}."
    )
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
