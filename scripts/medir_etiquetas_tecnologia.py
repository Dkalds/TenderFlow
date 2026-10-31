"""Mide cuántas etiquetas de tecnología lleva cada licitación, y con qué precisión.

Por qué existe
--------------
«El modelo pone demasiadas etiquetas» (2026-10-30) no tenía cifra: nadie había
contado cuántas lleva cada licitación ni de qué fuente sale cada una. Sin esa
cifra no se sabe si un cambio de reglas ayuda. Tres subcomandos:

``resumen``
    Reparto del número de etiquetas por licitación según cada vista
    —``tecnologia`` (título), ``ml_tecnologias`` (lo que filtran el Radar y la
    analítica), el bloque «Tecnologías» del detalle **antes** del 2026-10-30
    (todo lo que puntuaba) y **ahora** (solo lo que cada fuente predice)— y,
    por etiqueta, cuántas veces llega sin estar en el título. Termina con los
    términos que más sostienen etiquetas que solo vienen del pliego:
    candidatos a ``config.keywords.KEYWORDS_AMBIGUAS``, que se añaden por un
    ejemplo real, no por sospecha.

``muestra``
    Escribe un JSONL con ``--n`` licitaciones al azar (semilla fija) y, por
    cada etiqueta, ``"correcta": null`` para rellenar a mano (``true``/``false``);
    ``"faltan"`` admite las etiquetas que deberían estar y no están.

``precision``
    Lee ese JSONL revisado y da la precisión por etiqueta y por fuente.

``repuntuar`` y ``rehacer``
    **Escriben en la BD.** Aplican las reglas a lo ya guardado. ``repuntuar``
    vuelve a puntuar las licitaciones con alguna señal de pliego fundible
    (``score >= PLIEGO_TECH_MIN_SCORE``) de otra versión —las únicas que pueden
    haber dejado etiquetas viejas; el resto lo re-puntúa sin prisa el cron de
    ``pliegos.yml``—, repartible en ``--shards`` jobs paralelos. ``rehacer``,
    solo si ya no queda ninguna, rehace ``licitacion_tecnologia_score``
    (``precompute_ml_tecnologias(force=True)``) y vuelve a fundir los pliegos
    (``merge_doc_signals``): rehacer antes volvería a fundir las señales viejas.

Uso::

    ENV=prod PYTHONPATH="$PWD" python -m scripts.medir_etiquetas_tecnologia resumen
    ENV=prod PYTHONPATH="$PWD" python -m scripts.medir_etiquetas_tecnologia muestra \\
        --n 100 --out data/etiquetado/muestra_etiquetas.jsonl
    python -m scripts.medir_etiquetas_tecnologia precision data/etiquetado/muestra_etiquetas.jsonl
    ENV=prod PYTHONPATH="$PWD" python -m scripts.medir_etiquetas_tecnologia repuntuar
    ENV=prod PYTHONPATH="$PWD" python -m scripts.medir_etiquetas_tecnologia rehacer

``resumen`` y ``muestra`` leen la base de datos (solo lectura); ``precision``
solo el fichero. En producción se lanzan desde
``.github/workflows/etiquetas-tecnologia.yml``.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

#: Fuentes de una etiqueta, en el orden en que se enseñan.
FUENTE_TITULO = "titulo"
FUENTE_ML = "ml"
FUENTE_PLIEGO = "pliego"

#: Métodos de pliego que el bloque del detalle enseña con campo propio.
_METODOS_PLIEGO = ("keywords", "llm")


def _csv(valor: Any) -> set[str]:  # Any: celda cruda de la BD (str/None)
    return {t.strip() for t in str(valor or "").split(",") if t.strip()}


def _terminos(valor: Any) -> list[str]:  # Any: JSON en texto, lista o None
    if isinstance(valor, list):
        return [str(t) for t in valor]
    if not valor:
        return []
    try:
        cargado = json.loads(str(valor))
    except ValueError:
        return []
    return [str(t) for t in cargado] if isinstance(cargado, list) else []


def vistas(fila: dict[str, Any], *, min_pliego: float) -> dict[str, set[str]]:
    """Las etiquetas de una licitación según cada vista que se mide."""
    titulo = _csv(fila.get("tecnologia"))
    puntuadas = {
        str(s["tecnologia"])
        for s in fila.get("ml_scores") or []
        if float(s.get("probabilidad") or 0.0) > 0.0
    }
    pliego_todo = {str(p["tecnologia"]) for p in fila.get("pliego") or []}
    return {
        "titulo": titulo,
        "ml_tecnologias": _csv(fila.get("ml_tecnologias")),
        "detalle_antes": titulo | puntuadas | pliego_todo,
        "detalle_ahora": set(fuentes_por_etiqueta(fila, min_pliego=min_pliego)),
    }


def fuentes_por_etiqueta(fila: dict[str, Any], *, min_pliego: float) -> dict[str, list[str]]:
    """``{etiqueta: [fuentes]}`` de lo que hoy se enseña en el detalle."""
    titulo = _csv(fila.get("tecnologia"))
    out: dict[str, set[str]] = {}
    for tec in titulo:
        out.setdefault(tec, set()).add(FUENTE_TITULO)
    for s in fila.get("ml_scores") or []:
        prob = float(s.get("probabilidad") or 0.0)
        if prob >= float(s.get("threshold_aplicado") or 0.0):
            out.setdefault(str(s["tecnologia"]), set()).add(FUENTE_ML)
    for p in fila.get("pliego") or []:
        if p.get("method") in _METODOS_PLIEGO and float(p.get("score") or 0.0) >= min_pliego:
            out.setdefault(str(p["tecnologia"]), set()).add(FUENTE_PLIEGO)
    return {tec: sorted(f) for tec, f in sorted(out.items())}


def resumir(filas: list[dict[str, Any]], *, min_pliego: float) -> dict[str, Any]:
    """Recuento de :func:`vistas` sobre todas las filas. Puro, sin BD."""
    reparto: dict[str, Counter[int]] = {}
    por_etiqueta: dict[str, Counter[str]] = {}
    terminos_solo_pliego: Counter[str] = Counter()
    for fila in filas:
        v = vistas(fila, min_pliego=min_pliego)
        for nombre, etiquetas in v.items():
            reparto.setdefault(nombre, Counter())[len(etiquetas)] += 1
            for tec in etiquetas:
                por_etiqueta.setdefault(tec, Counter())[nombre] += 1
        for tec in v["ml_tecnologias"] - v["titulo"]:
            por_etiqueta.setdefault(tec, Counter())["sin_titulo"] += 1
        for p in fila.get("pliego") or []:
            if p.get("method") == "keywords" and str(p["tecnologia"]) not in v["titulo"]:
                for termino in _terminos(p.get("matched_terms")):
                    terminos_solo_pliego[f"{p['tecnologia']}: {termino}"] += 1
    return {
        "n": len(filas),
        "reparto": {k: dict(sorted(c.items())) for k, c in reparto.items()},
        "media": {
            k: (sum(n * c for n, c in cont.items()) / max(len(filas), 1))
            for k, cont in reparto.items()
        },
        "por_etiqueta": {k: dict(c) for k, c in sorted(por_etiqueta.items())},
        "terminos_solo_pliego": terminos_solo_pliego.most_common(30),
    }


def muestra(
    filas: list[dict[str, Any]], *, n: int, min_pliego: float, semilla: int = 20261030
) -> list[dict[str, Any]]:
    """``n`` licitaciones al azar, con sus etiquetas listas para revisar."""
    elegidas = random.Random(semilla).sample(filas, min(n, len(filas)))  # noqa: S311 - muestreo, no cripto
    lineas: list[dict[str, Any]] = []
    for fila in elegidas:
        fuentes = fuentes_por_etiqueta(fila, min_pliego=min_pliego)
        if not fuentes:
            continue
        lineas.append(
            {
                "id": fila["id_externo"],
                "titulo": fila.get("titulo"),
                "cpv": fila.get("cpv"),
                "etiquetas": {tec: {"fuentes": f, "correcta": None} for tec, f in fuentes.items()},
                "faltan": [],
            }
        )
    return lineas


def precision(lineas: list[dict[str, Any]]) -> dict[str, Any]:
    """Precisión por etiqueta y por fuente de un JSONL revisado. Puro."""
    por_etiqueta: dict[str, list[int]] = {}
    por_fuente: dict[str, list[int]] = {}
    revisadas = sin_revisar = 0
    faltan: Counter[str] = Counter()
    for linea in lineas:
        faltan.update(str(t) for t in linea.get("faltan") or [])
        for tec, info in (linea.get("etiquetas") or {}).items():
            correcta = info.get("correcta")
            if correcta is None:
                sin_revisar += 1
                continue
            revisadas += 1
            acierto = 1 if correcta else 0
            por_etiqueta.setdefault(tec, [0, 0])[0] += acierto
            por_etiqueta[tec][1] += 1
            for fuente in info.get("fuentes") or []:
                por_fuente.setdefault(fuente, [0, 0])[0] += acierto
                por_fuente[fuente][1] += 1
            if info.get("fuentes") == [FUENTE_PLIEGO]:
                por_fuente.setdefault("solo_pliego", [0, 0])[0] += acierto
                por_fuente["solo_pliego"][1] += 1
    aciertos = sum(a for a, _ in por_etiqueta.values())
    return {
        "revisadas": revisadas,
        "sin_revisar": sin_revisar,
        "precision_global": aciertos / revisadas if revisadas else None,
        "por_etiqueta": {k: (a / t, t) for k, (a, t) in sorted(por_etiqueta.items())},
        "por_fuente": {k: (a / t, t) for k, (a, t) in sorted(por_fuente.items())},
        "faltan": dict(faltan.most_common()),
    }


def _imprimir_resumen(r: dict[str, Any]) -> None:
    print(f"Licitaciones con alguna etiqueta: {r['n']}")
    print("\nEtiquetas por licitación (media y reparto n_etiquetas: licitaciones):")
    for vista, reparto in r["reparto"].items():
        print(f"  {vista:15} media {r['media'][vista]:.2f}  {reparto}")
    print("\nPor etiqueta (veces en cada vista; sin_titulo = en ml_tecnologias y no en el título):")
    for tec, cuentas in r["por_etiqueta"].items():
        print(f"  {tec:20} {cuentas}")
    print("\nTérminos que más sostienen etiquetas de pliego que el título no tiene:")
    for termino, veces in r["terminos_solo_pliego"]:
        print(f"  {veces:6}  {termino}")


def _imprimir_precision(r: dict[str, Any]) -> None:
    global_ = r["precision_global"]
    print(f"Etiquetas revisadas: {r['revisadas']} (sin revisar: {r['sin_revisar']})")
    print(f"Precisión global: {global_:.1%}" if global_ is not None else "Precisión global: —")
    print("\nPor fuente (precisión, etiquetas):")
    for fuente, (p, t) in r["por_fuente"].items():
        print(f"  {fuente:12} {p:6.1%}  {t}")
    print("\nPor etiqueta (precisión, etiquetas):")
    for tec, (p, t) in r["por_etiqueta"].items():
        print(f"  {tec:20} {p:6.1%}  {t}")
    if r["faltan"]:
        print(f"\nEtiquetas que faltaban: {r['faltan']}")


def _obsoletas(*, shard: int = 0, shards: int = 1, limite: int) -> list[str]:
    from config import settings
    from db.repositories.tecnologia_pliego import TecnologiaPliegoRepository
    from scraper.lineage import current_filter_version

    return TecnologiaPliegoRepository().licitaciones_con_senal_obsoleta(
        signal_version=current_filter_version(),
        min_score=float(settings.PLIEGO_TECH_MIN_SCORE),
        shard=shard,
        shards=shards,
        limit=limite,
    )


def repuntuar(
    *, presupuesto_s: float, shard: int = 0, shards: int = 1, lote: int = 100
) -> dict[str, Any]:
    """Re-puntúa las licitaciones con señal de pliego fundible de otra versión.

    Solo esas: son las únicas cuyas señales viejas pueden haber dejado
    etiquetas en ``licitacion_tecnologia_score``. ``quedan`` dice si se paró
    con trabajo pendiente (presupuesto agotado o un lote que solo falla).
    """
    import time

    from scheduler.jobs.documentos_embeddings import _run_tech_signal_phase

    inicio = time.monotonic()
    pliegos: Counter[str] = Counter()
    quedan = True
    while time.monotonic() - inicio < presupuesto_s:
        ids = _obsoletas(shard=shard, shards=shards, limite=lote)
        if not ids:
            quedan = False
            break
        hecho = _run_tech_signal_phase(licitacion_ids=ids)
        pliegos.update(hecho)
        # Las que fallan siguen obsoletas: un lote que solo falla no avanza, y
        # otra vuelta lo repetiría hasta agotar el presupuesto.
        if not (hecho.get("scored", 0) or hecho.get("no_signal", 0)):
            break
    return {"pliegos": dict(pliegos), "quedan": quedan}


def rehacer() -> dict[str, Any]:
    """Rehace ``licitacion_tecnologia_score`` y funde los pliegos, si se puede.

    Antes comprueba que no quede ninguna señal fundible de otra versión:
    rehacer con alguna volvería a fundir la etiqueta que se quiere quitar.
    """
    from services.ml.classifier_training import precompute_ml_tecnologias
    from services.tech_signal import merge_doc_signals

    if _obsoletas(limite=1):
        return {"completo": False}
    return {
        "completo": True,
        "ml": precompute_ml_tecnologias(force=True),
        "fusion": merge_doc_signals(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else None)
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("resumen", help="reparto de etiquetas por licitación y por fuente")
    p_muestra = sub.add_parser("muestra", help="JSONL para revisar a mano")
    p_muestra.add_argument("--n", type=int, default=100)
    p_muestra.add_argument("--out", type=Path, required=True)
    p_precision = sub.add_parser("precision", help="precisión de un JSONL revisado")
    p_precision.add_argument("fichero", type=Path)
    p_repuntuar = sub.add_parser("repuntuar", help="ESCRIBE: re-puntúa los pliegos obsoletos")
    p_repuntuar.add_argument("--presupuesto-s", type=float, default=2700.0)
    p_repuntuar.add_argument("--shard", type=int, default=0)
    p_repuntuar.add_argument("--shards", type=int, default=1)
    sub.add_parser("rehacer", help="ESCRIBE: rehace las puntuaciones ML y funde los pliegos")
    args = parser.parse_args(argv)

    if args.comando == "precision":
        lineas = [
            json.loads(linea)
            for linea in args.fichero.read_text(encoding="utf-8").splitlines()
            if linea.strip()
        ]
        _imprimir_precision(precision(lineas))
        return 0

    if args.comando in ("repuntuar", "rehacer"):
        hecho = (
            repuntuar(presupuesto_s=args.presupuesto_s, shard=args.shard, shards=args.shards)
            if args.comando == "repuntuar"
            else rehacer()
        )
        print(json.dumps(hecho, ensure_ascii=False, indent=2, default=str))
        if hecho.get("quedan") or hecho.get("completo") is False:
            print("Quedan pliegos obsoletos: vuelve a lanzar el modo recalcular.", file=sys.stderr)
        return 0

    from config import settings
    from db.repositories.medicion_etiquetas import filas_etiquetas_tecnologia

    min_pliego = float(settings.PLIEGO_TECH_MIN_SCORE)
    filas = filas_etiquetas_tecnologia()
    if args.comando == "resumen":
        _imprimir_resumen(resumir(filas, min_pliego=min_pliego))
        return 0

    lineas = muestra(filas, n=args.n, min_pliego=min_pliego)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        "".join(json.dumps(linea, ensure_ascii=False) + "\n" for linea in lineas),
        encoding="utf-8",
    )
    print(f"{len(lineas)} licitaciones escritas en {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
