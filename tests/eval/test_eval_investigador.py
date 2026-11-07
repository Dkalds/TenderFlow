"""Eval de recuperación del Investigador por tipo de consulta (lista y ``/ask``).

``test_eval_rag.py`` no distingue una versión buena de una mala: sus 15
preguntas repiten en el título un nombre en clave inventado («Fénix»,
«Nébula») y cualquier motor las acierta (MRR = 1.0 desde 2026-10). No mide lo
que hace difícil este buscador: lo que solo dice el pliego, los filtros
escritos dentro de la frase, lo abierto frente a lo adjudicado, la pregunta
hablada, la tilde que falta ni la paráfrasis.

Aquí cada consulta lleva su **categoría** y el MRR se publica por categoría,
para que un cambio de ranking —o encender la búsqueda por significado (backlog
P2 «[Investigador] búsqueda por significado»)— se lea donde mueve algo. Mide
además cuántas veces el expediente esperado llega al modelo de ``/ask`` **con
un fragmento de su pliego**, que es lo que el asistente puede citar.

Límite conocido: el corpus (``fixtures/eval_investigador.json``) imita
expedientes reales —títulos, órganos, cláusulas de pliego— pero es sembrado, y
los juicios de relevancia los escribió quien preparó el set, no el equipo de
preventa. shortcut: juicios propios sobre un corpus sembrado, sustituirlos por
consultas reales de preventa juzgadas contra una copia de producción en cuanto
haya una sesión para recogerlas. Hasta entonces, ninguna categoría se da por
medida con menos de dos consultas.

Corre ``search_for_ask``, que desde 2026-11 es exactamente la búsqueda de la
lista (``services.investigador.busqueda.buscar``) más el contexto del
asistente, con la flag de significado apagada: el camino que sirve hoy.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from tests.eval.test_eval_rag import _publicar, _reciprocal_rank

_FIXTURE = Path(__file__).parent / "fixtures" / "eval_investigador.json"
TOP_K = 5

# Suelos medidos el 2026-11-07 en Postgres 16 local, tres corridas idénticas;
# «antes» es master justo antes de este cambio (misma prueba, mismo corpus):
#
#   categoría            antes    ahora
#   filtros              1.000    1.000
#   pliego               1.000    1.000
#   vigencia             0.500    1.000   ← lo abierto delante a igual coincidencia
#   parcial              0.750    0.750   ← ver abajo
#   hablada              1.000    1.000
#   tilde                1.000    1.000
#   parafrasis           0.333    0.333   ← solo texto: la línea base del significado
#   global               0.816    0.868
#   pliego en contexto   0.455    1.000   ← el expediente esperado llega con pliego
#
# «parcial» falla en «mantenimiento SAP hospital»: el contrato de ascensores
# del hospital sale primero porque «hospital» es raro entre los candidatos y
# pesa más que «SAP» (``anuncios_por_terminos`` pondera por rareza). Es un
# defecto del ranking, no del set: se arregla en el ranking y entonces sube el
# suelo, no al revés.
#
# Un suelo es lo medido: si una consulta baja de puesto, se mira por qué antes
# de tocar el número.
MRR_MIN_GLOBAL = 0.86
MRR_MIN_POR_CATEGORIA = {
    "filtros": 1.0,
    "pliego": 1.0,
    "vigencia": 1.0,
    "parcial": 0.75,
    "hablada": 1.0,
    "tilde": 1.0,
    "parafrasis": 0.33,
}
PLIEGO_EN_CONTEXTO_MIN = 1.0


def _cargar() -> dict[str, Any]:
    datos: dict[str, Any] = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return datos


def _sembrar(licitaciones: list[dict[str, Any]]) -> None:
    """Expedientes y sus pliegos (SQL directo para los fragmentos: es un
    fixture de datos, ``tests/*`` está fuera del TID251)."""
    from db.database import connect
    from db.upsert import Licitacion, upsert_licitaciones

    upsert_licitaciones(
        [Licitacion(**{k: v for k, v in lic.items() if k != "pliego"}) for lic in licitaciones]
    )
    with connect() as c:
        for lic in licitaciones:
            if not lic.get("pliego"):
                continue
            documento_id = c.execute(
                "INSERT INTO documentos (licitacion_id, tipo, uri, filename, status, texto) "
                "VALUES (%s, 'legal', %s, 'PCAP.pdf', 'extracted', %s) RETURNING id",
                (
                    lic["id_externo"],
                    f"https://example.com/{lic['id_externo']}.pdf",
                    "\n".join(lic["pliego"]),
                ),
            ).fetchone()[0]
            for i, texto in enumerate(lic["pliego"]):
                c.execute(
                    "INSERT INTO documento_chunks (documento_id, chunk_index, texto, page_number) "
                    "VALUES (%s, %s, %s, %s)",
                    (documento_id, i, texto, i + 1),
                )


def _medir(datos: dict[str, Any]) -> tuple[dict[str, float], float, float, list[str]]:
    """``(MRR por categoría, MRR global, pliego en contexto, fallos)``."""
    from services.licitaciones import search_for_ask

    con_pliego = {lic["id_externo"] for lic in datos["licitaciones"] if lic.get("pliego")}
    por_categoria: dict[str, list[float]] = defaultdict(list)
    con_fragmento: list[bool] = []
    fallos: list[str] = []
    for consulta in datos["consultas"]:
        esperados = set(consulta["esperados"])
        docs = search_for_ask(consulta["q"], TOP_K)
        ids = [d["id_externo"] for d in docs]
        rr = _reciprocal_rank(ids, esperados)
        por_categoria[consulta["categoria"]].append(rr)
        if rr < 1.0:
            fallos.append(f"[{consulta['categoria']}] {consulta['q']!r} -> {ids}")
        for doc in docs:
            if doc["id_externo"] in esperados and doc["id_externo"] in con_pliego:
                con_fragmento.append(bool(doc.get("chunks")))
    mrr = {cat: sum(v) / len(v) for cat, v in sorted(por_categoria.items())}
    todos = [rr for v in por_categoria.values() for rr in v]
    cobertura = sum(con_fragmento) / len(con_fragmento) if con_fragmento else 0.0
    return mrr, sum(todos) / len(todos), cobertura, fallos


def test_el_set_cubre_cada_categoria_con_al_menos_dos_consultas() -> None:
    datos = _cargar()
    ids = {lic["id_externo"] for lic in datos["licitaciones"]}
    por_categoria: dict[str, int] = defaultdict(int)
    for consulta in datos["consultas"]:
        por_categoria[consulta["categoria"]] += 1
        assert set(consulta["esperados"]) <= ids, consulta
    assert set(por_categoria) == set(MRR_MIN_POR_CATEGORIA)
    assert min(por_categoria.values()) >= 2, dict(por_categoria)


def test_mrr_por_categoria_y_pliego_en_contexto(tmp_db: Any) -> None:
    datos = _cargar()
    _sembrar(datos["licitaciones"])

    mrr, global_, cobertura, fallos = _medir(datos)

    lineas = [f"  {cat:<12} MRR={valor:.3f}" for cat, valor in mrr.items()]
    _publicar(
        "\neval_investigador:\n"
        + "\n".join(lineas)
        + f"\n  global       MRR={global_:.3f}"
        + f"\n  pliego en contexto de /ask = {cobertura:.3f}"
    )
    for fallo in fallos:
        print(f"    - {fallo}")

    assert global_ >= MRR_MIN_GLOBAL, f"MRR global {global_:.3f}; fallos: {fallos}"
    for categoria, suelo in MRR_MIN_POR_CATEGORIA.items():
        assert mrr[categoria] >= suelo, (
            f"MRR de {categoria} {mrr[categoria]:.3f} < {suelo}; fallos: {fallos}"
        )
    assert cobertura >= PLIEGO_EN_CONTEXTO_MIN, (
        f"solo {cobertura:.0%} de los expedientes esperados con pliego llegan a /ask con él"
    )
