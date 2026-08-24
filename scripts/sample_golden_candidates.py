"""Muestrea candidatos para ampliar el golden set del clasificador SAP.

Por qué hace falta
------------------
El golden set (``tests/fixtures/golden_set.jsonl``) es el único sitio del repo
con etiquetas **humanas** independientes del filtro de keywords, y de él salen
dos cosas: el umbral que se sirve en producción y ``recall_no_keyword``, la
métrica que mide si el ML aporta algo sobre ``matches_sap()``.

Con los 27 ejemplos actuales no sostiene ninguna de las dos:

- Solo 6 son positivos humanos sin keyword, así que ``recall_no_keyword`` se
  mueve a saltos de 16,7 puntos y únicamente puede tomar 7 valores.
- Un bootstrap sobre esos 27 da un umbral con sigma = 0,084 y un rango
  p5-p95 de [0,30, 0,56] — sobre un rango útil de 0,65. Y el F-beta que se
  guardaba en la metadata sobreestimaba el real en +0,08 de media (+0,25 en el
  p90), por elegir el umbral y reportar sobre el mismo conjunto.

``services.ml_eval`` ya parte el golden en mitades ``tune``/``holdout`` para
que el umbral no se elija donde se reporta, pero partir 27 en dos no arregla el
tamaño: hacen falta del orden de 300-500 ejemplos (>= 60 por mitad, ver
``MIN_TUNE_EXAMPLES``/``MIN_HOLDOUT_EXAMPLES``).

Qué hace este script
--------------------
**No etiqueta**: no puede. Selecciona *qué* conviene mandar a etiquetar y
escribe un JSONL con ``label: null`` listo para que una persona lo rellene.

El muestreo es estratificado y deliberadamente **sesgado hacia la zona de
desacuerdo** — los casos donde las keywords y el modelo no coinciden. Un
ejemplo donde ambos dicen lo mismo casi no aporta información: lo que decide la
calidad del umbral y de ``recall_no_keyword`` son los desacuerdos.

Uso::

    python -m scripts.sample_golden_candidates --n 400 --out /tmp/candidatos.jsonl

Después: etiquetar ``label`` a mano (1 = es SAP, 0 = no), revisar
``keyword_match`` y anexar las líneas a ``tests/fixtures/golden_set.jsonl``.
El campo ``split`` se puede dejar vacío: ``services.ml_eval.asignar_splits`` lo
reparte por hash del ``id`` de forma estable, así que añadir ejemplos nuevos no
reasigna los que ya estaban.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# Cuántos ejemplos pedir de cada estrato, en proporción. La zona de desacuerdo
# pesa el triple que la de acuerdo: es donde se decide si el ML aporta.
_PESOS_ESTRATO: dict[str, float] = {
    "desacuerdo_modelo_si_keyword_no": 3.0,
    "desacuerdo_modelo_no_keyword_si": 3.0,
    "frontera_modelo_indeciso": 2.0,
    "acuerdo_positivo": 1.0,
    "acuerdo_negativo": 1.0,
}
_BANDA_BAJA = 0.30
_BANDA_ALTA = 0.70


def _estrato(proba: float | None, keyword_match: bool) -> str:
    """Clasifica un candidato en su estrato de muestreo."""
    if proba is None:
        return "acuerdo_positivo" if keyword_match else "acuerdo_negativo"
    if _BANDA_BAJA <= proba < _BANDA_ALTA:
        return "frontera_modelo_indeciso"
    if proba >= _BANDA_ALTA and not keyword_match:
        return "desacuerdo_modelo_si_keyword_no"
    if proba < _BANDA_BAJA and keyword_match:
        return "desacuerdo_modelo_no_keyword_si"
    return "acuerdo_positivo" if keyword_match else "acuerdo_negativo"


def _cuotas(n_total: int, disponibles: dict[str, int]) -> dict[str, int]:
    """Reparte ``n_total`` entre estratos según pesos, sin pedir más de lo que hay."""
    pendientes = {k: v for k, v in disponibles.items() if v > 0}
    cuotas: dict[str, int] = {}
    restante = n_total
    while pendientes and restante > 0:
        peso_total = sum(_PESOS_ESTRATO.get(k, 1.0) for k in pendientes)
        asignado_ronda = 0
        for estrato in list(pendientes):
            objetivo = int(restante * _PESOS_ESTRATO.get(estrato, 1.0) / peso_total)
            toma = min(objetivo, pendientes[estrato])
            if toma <= 0:
                continue
            cuotas[estrato] = cuotas.get(estrato, 0) + toma
            pendientes[estrato] -= toma
            asignado_ronda += toma
            if pendientes[estrato] == 0:
                del pendientes[estrato]
        restante -= asignado_ronda
        if asignado_ronda == 0:
            break
    return cuotas


def _cargar_candidatos(pool: int) -> list[dict[str, Any]]:
    """Trae candidatos sin feedback humano desde el repositorio de licitaciones."""
    from db.repositories.licitaciones import LicitacionRepository

    return LicitacionRepository().get_unlabelled_candidates(limit=pool)


def _puntuar(candidatos: list[dict[str, Any]]) -> list[float | None]:
    """Puntúa con el clasificador activo; ``None`` si no hay modelo disponible."""
    try:
        from scraper.ml_classifier import SAPClassifier

        if not SAPClassifier.is_available():
            print("[aviso] no hay modelo disponible: se muestreará sin banda de probabilidad")
            return [None] * len(candidatos)
        clf = SAPClassifier.load()
        probas = clf.predict_proba(
            [f"{c.get('titulo') or ''} {c.get('descripcion') or ''}".strip() for c in candidatos],
            cpvs=[(str(c["cpv"]) if c.get("cpv") is not None else None) for c in candidatos],
            importes=[
                (float(c["importe"]) if c.get("importe") is not None else None) for c in candidatos
            ],
        )
        return [float(p[1]) for p in probas]
    except Exception as exc:  # pragma: no cover — el muestreo no debe morir por esto
        print(f"[aviso] no se pudo puntuar con el modelo ({exc}); se sigue sin probabilidades")
        return [None] * len(candidatos)


def _keyword_match(candidato: dict[str, Any]) -> bool:
    """¿Lo detectaría el filtro de keywords? Es el eje del muestreo."""
    from scraper.filters import matches_sap

    encontrado, _ = matches_sap(
        str(candidato.get("titulo") or ""),
        "",
        str(candidato.get("descripcion") or ""),
    )
    return bool(encontrado)


def muestrear(n: int, pool: int, seed: int) -> list[dict[str, Any]]:
    """Devuelve ``n`` candidatos estratificados, listos para etiquetar a mano."""
    candidatos = _cargar_candidatos(pool)
    if not candidatos:
        return []
    probas = _puntuar(candidatos)

    por_estrato: dict[str, list[tuple[dict[str, Any], float | None, bool]]] = defaultdict(list)
    for candidato, proba in zip(candidatos, probas, strict=True):
        kw = _keyword_match(candidato)
        por_estrato[_estrato(proba, kw)].append((candidato, proba, kw))

    rng = random.Random(seed)  # noqa: S311 — muestreo reproducible, no criptografía
    for filas in por_estrato.values():
        rng.shuffle(filas)

    cuotas = _cuotas(n, {k: len(v) for k, v in por_estrato.items()})
    print("Reparto por estrato:")
    for estrato in sorted(por_estrato):
        print(
            f"  {estrato:38s} disponibles={len(por_estrato[estrato]):5d} "
            f"seleccionados={cuotas.get(estrato, 0):4d}"
        )

    salida: list[dict[str, Any]] = []
    for estrato, cuota in cuotas.items():
        for candidato, proba, kw in por_estrato[estrato][:cuota]:
            salida.append(
                {
                    "id": str(candidato.get("id_externo") or ""),
                    "titulo": str(candidato.get("titulo") or ""),
                    "descripcion": str(candidato.get("descripcion") or ""),
                    "label": None,  # ← lo rellena una persona: 1 = SAP, 0 = no
                    "cpv": candidato.get("cpv"),
                    "importe": candidato.get("importe"),
                    "keyword_match": kw,
                    "split": "",  # asignado por hash al cargar
                    "note": (
                        f"PENDIENTE DE ETIQUETAR · estrato={estrato}"
                        + (f" · ml_proba={proba:.3f}" if proba is not None else "")
                    ),
                }
            )
    return salida


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=400, help="candidatos a muestrear")
    parser.add_argument("--pool", type=int, default=5000, help="filas a considerar")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, required=True, help="JSONL de salida")
    args = parser.parse_args(argv)

    filas = muestrear(args.n, args.pool, args.seed)
    if not filas:
        print("No hay candidatos sin etiquetar en la BD.", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        fh.write("# Candidatos para ampliar el golden set. `label` está a null: rellenar a mano.\n")
        fh.write("# 1 = la licitación es una oportunidad SAP · 0 = no lo es.\n")
        fh.write("# Revisar tambien `keyword_match` antes de anexar a golden_set.jsonl.\n")
        for fila in filas:
            fh.write(json.dumps(fila, ensure_ascii=False) + "\n")

    print(f"\n{len(filas)} candidatos escritos en {args.out}")
    print("Siguiente paso: etiquetar `label` a mano y anexar a tests/fixtures/golden_set.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
