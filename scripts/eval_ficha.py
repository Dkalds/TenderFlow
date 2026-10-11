"""Eval de la ficha del pliego contra el golden, con el LLM real.

Por qué existe
--------------
La extracción de la ficha (``services/rag/fact_sheet.py``) se cambiaba
comparando a ojo unos pocos pliegos. Este script ejecuta el camino de
producción —selector de páginas, pregunta, modelo y validación de citas— sobre
los pliegos de ``tests/fixtures/fichas/`` y dice, por familia, cuánto de lo
que extrae es cierto y cuánto de lo cierto extrae.

Es el control que se ejecuta, y cuyo resultado se pega en el PR, **antes de
tocar el prompt, el modelo, el selector o la validación de citas**.

Llama al modelo de verdad: no es determinista y cuesta una extracción por caso.
Por eso vive fuera de CI (RFC llm-dependencia-gestionada §3). Lo que sí corre en
CI es la parte sin modelo: ``tests/eval/test_eval_ficha_selector.py``.

**No usa base de datos**, y arranca con ``DATABASE_URL`` vacía para que no
pueda: los casos son ficheros.

Cómo leer el resultado
----------------------
- **Casos completos** (alguien leyó el pliego entero): precisión y cobertura
  estrictas.
- **Casos parciales** (solo se revisó lo extraído): un hecho que nadie revisó
  sale como «sin juzgar», no como error; «conservados» es cuánto de lo que ya
  se sabía cierto sigue encontrándose.
- Una familia con menos de diez positivos dice «sin datos suficientes» en vez
  de un porcentaje.

Uso
---
::

    make eval-ficha
    python scripts/eval_ficha.py --model <modelo>     # comparar otro modelo
    python scripts/eval_ficha.py --check              # 1 si baja de los mínimos
    python scripts/eval_ficha.py --pendientes         # deja lo «sin juzgar» para revisar
    python scripts/eval_ficha.py --fijar-minimos      # tres ejecuciones; escribe minimos.json

El diseño completo está en ``docs/plans/2026-10-eval-ficha-pliego.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

_RAIZ_REPO = Path(__file__).resolve().parent.parent
if str(_RAIZ_REPO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_REPO))

from llm.client import DEFAULT_MODEL  # noqa: E402
from services.rag.fact_sheet import (  # noqa: E402
    EXTRACTION_VERSION,
    ExtraccionHechos,
    _select_pages,
    extraer_hechos,
)
from services.rag.ficha_eval import (  # noqa: E402
    CLAVES_DE_MINIMOS,
    MIN_POSITIVOS_POR_FAMILIA,
    Informe,
    MetricasFamilia,
    ResultadoCaso,
    agregar,
    cobertura_selector,
    comprobar_minimos,
    medir_caso,
    minimos_desde,
)
from services.rag.ficha_golden import (  # noqa: E402
    FAMILIAS,
    escribir_pendientes,
    leer_caso,
    listar_casos,
    sin_revisar,
)

RAIZ_POR_DEFECTO = _RAIZ_REPO / "tests" / "fixtures" / "fichas"
NOMBRE_MINIMOS = "minimos.json"

#: Ejecuciones con las que se fija la base: el modelo no es determinista.
EJECUCIONES_DE_BASE = 3

Extractor = Callable[..., ExtraccionHechos]


def _sin_bd() -> None:
    """Deja el proceso sin base de datos: cualquier conexión falla al abrirse.

    Mismo motivo que en ``scripts/eval_rag_generation.py``: lanzado desde el
    checkout principal, ``DATABASE_URL`` apunta a producción. El eval no la
    necesita, así que no la tiene.
    """
    os.environ["DATABASE_URL"] = ""

    from pydantic import SecretStr

    from config import settings

    settings.DATABASE_URL = SecretStr("")


def evaluar(
    raiz: Path,
    *,
    model: str,
    solo: str | None = None,
    extraer: Extractor | None = None,
) -> tuple[Informe, list[ResultadoCaso], dict[str, tuple[int, int]]]:
    """Ejecuta la extracción sobre cada caso y la mide.

    Devuelve el informe agregado, el resultado de cada caso y la cobertura del
    selector de páginas sumada por familia. Un caso con veredictos pendientes
    se salta —medir contra un golden a medias daría un número sin sentido—; uno
    cuya extracción falla **no**: se cuenta como fallido.
    """
    extractor = extraer or extraer_hechos
    resultados: list[ResultadoCaso] = []
    selector: dict[str, tuple[int, int]] = {}
    for carpeta in listar_casos(raiz):
        if solo is not None and carpeta.name != solo:
            continue
        caso = leer_caso(carpeta)
        if pendientes := sin_revisar(caso.golden):
            print(
                f"Aviso: el caso {caso.nombre} tiene {pendientes} hechos sin veredicto y no "
                f"se evalúa. Revísalo: python scripts/revisar_ficha_golden.py {caso.nombre}",
                file=sys.stderr,
            )
            continue
        try:
            extraccion = extractor(
                caso.paginas, licitacion_id=caso.golden.licitacion_id, model=model
            )
        except Exception as exc:
            # Cualquier fallo de la extracción es un dato del eval, no un
            # motivo para dejar de medir los demás casos.
            resultados.append(medir_caso(caso, None, fallo=str(exc)[:300]))
        else:
            resultados.append(medir_caso(caso, extraccion))
        # El selector es determinista y no depende de que el modelo responda.
        for familia, (cubiertos, total) in cobertura_selector(
            caso, _select_pages(caso.paginas)
        ).items():
            previos = selector.get(familia, (0, 0))
            selector[familia] = (previos[0] + cubiertos, previos[1] + total)
    return agregar(resultados), resultados, selector


def _selector_total(selector: Mapping[str, tuple[int, int]]) -> float | None:
    cubiertos = sum(c for c, _ in selector.values())
    total = sum(t for _, t in selector.values())
    return None if total == 0 else cubiertos / total


def _pct(valor: float | None) -> str:
    return "—" if valor is None else f"{valor * 100:.1f} %".replace(".", ",")


def _tabla(por_familia: Mapping[str, MetricasFamilia], *, completos: bool) -> list[str]:
    ultima = "f.pos" if completos else "s.juz"
    lineas = [
        f"{'familia':22} {'extr':>5} {'posit':>5} {'acier':>5} {'v.dist':>6} {'err':>4} "
        f"{'dupl':>4} {ultima:>5}  {'precisión' if completos else 'conservados':>11}  "
        f"{'cobertura' if completos else '':>9}"
    ]
    total = MetricasFamilia()
    for familia in FAMILIAS:
        m = por_familia.get(familia, MetricasFamilia())
        if not (m.extraidos or m.positivos):
            continue
        total = total + m
        lineas.append(_fila(familia, m, completos=completos, exigir_poblacion=True))
    lineas.append(_fila("TOTAL", total, completos=completos, exigir_poblacion=False))
    return lineas


def _fila(nombre: str, m: MetricasFamilia, *, completos: bool, exigir_poblacion: bool) -> str:
    ultima = m.falsos_positivos if completos else m.sin_juzgar
    recuentos = (
        f"{nombre:22} {m.extraidos:>5} {m.positivos:>5} {m.aciertos:>5} "
        f"{m.valor_distinto:>6} {m.errores_confirmados:>4} {m.duplicados:>4} {ultima:>5}"
    )
    if exigir_poblacion and m.positivos < MIN_POSITIVOS_POR_FAMILIA:
        return f"{recuentos}  sin datos suficientes ({m.positivos} positivos)"
    if completos:
        return f"{recuentos}  {_pct(m.precision):>11}  {_pct(m.cobertura):>9}"
    return f"{recuentos}  {_pct(m.cobertura):>11}"


def formatear(informe: Informe, selector: Mapping[str, tuple[int, int]]) -> str:
    """El informe en texto, listo para pegarlo en un PR."""
    lineas = [
        f"Casos: {informe.n_completos} completos, {informe.n_parciales} parciales"
        f" · extracciones fallidas: {informe.casos_fallidos}"
        f" · vacías: {informe.extracciones_vacias}",
        f"Descartes del extractor: {informe.invalidos} por esquema, "
        f"{informe.inverificables} por cita no literal",
        "",
        "COMPLETOS — precisión y cobertura estrictas",
        *_tabla(informe.completos, completos=True),
        "",
        "PARCIALES — lo que nadie revisó es «sin juzgar», no un error",
        *_tabla(informe.parciales, completos=False),
        "",
        "SELECTOR — positivos cuya página entra en el contexto del modelo",
    ]
    for familia in FAMILIAS:
        if familia in selector:
            cubiertos, total = selector[familia]
            lineas.append(f"  {familia:20} {cubiertos:>4} / {total:<4}")
    lineas.append(f"  {'TOTAL':20} {_pct(_selector_total(selector))}")
    lineas.append("")
    lineas.append(
        "Totales: "
        + " · ".join(f"{clave} {_pct(valor)}" for clave, valor in informe.totales.items())
    )
    return "\n".join(lineas)


def _totales(informe: Informe, selector: Mapping[str, tuple[int, int]]) -> dict[str, float | None]:
    return {**informe.totales, "selector_cobertura": _selector_total(selector)}


def _leer_minimos(raiz: Path) -> dict[str, float] | None:
    ruta = raiz / NOMBRE_MINIMOS
    if not ruta.is_file():
        return None
    contenido = json.loads(ruta.read_text(encoding="utf-8"))
    return {str(clave): float(valor) for clave, valor in contenido.get("minimos", {}).items()}


def _escribir_pendientes(raiz: Path, resultados: list[ResultadoCaso]) -> None:
    for resultado in resultados:
        # Un caso cuya extracción falló no dice nada nuevo: sus pendientes de
        # una ejecución anterior siguen siendo los que hay que revisar.
        if resultado.completo or resultado.fallo is not None:
            continue
        escribir_pendientes(
            raiz / resultado.nombre,
            [(familia, hecho.model_dump(mode="json")) for familia, hecho in resultado.pendientes],
        )
        if resultado.pendientes:
            print(
                f"{resultado.nombre}: {len(resultado.pendientes)} hechos sin juzgar. "
                f"Revísalos: python scripts/revisar_ficha_golden.py {resultado.nombre}"
            )


def _escribir_salida(
    ruta: Path,
    informe: Informe,
    resultados: list[ResultadoCaso],
    totales: Mapping[str, float | None],
    model: str,
) -> None:
    def con_datos(por_familia: Mapping[str, MetricasFamilia]) -> dict[str, Any]:
        return {f: asdict(m) for f, m in por_familia.items() if m.extraidos or m.positivos}

    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps(
            {
                "medido_el": date.today().isoformat(),
                "model": model,
                "extraction_version": EXTRACTION_VERSION,
                "totales": dict(totales),
                "completos": con_datos(informe.completos),
                "parciales": con_datos(informe.parciales),
                "casos": [
                    {
                        "nombre": r.nombre,
                        "completo": r.completo,
                        "fallo": r.fallo,
                        "invalidos": r.invalidos,
                        "inverificables": r.inverificables,
                        "por_familia": con_datos(r.por_familia),
                    }
                    for r in resultados
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _fijar_minimos(raiz: Path, model: str) -> int:
    ejecuciones: list[dict[str, float | None]] = []
    selector: dict[str, tuple[int, int]] = {}
    for numero in range(1, EJECUCIONES_DE_BASE + 1):
        informe, resultados, selector = evaluar(raiz, model=model)
        if not resultados:
            return _sin_casos()
        print(f"\n── Ejecución {numero} de {EJECUCIONES_DE_BASE} ──")
        print(formatear(informe, selector))
        # La base se mide con todos los casos y todas las extracciones hechas:
        # una caída del proveedor o un caso a medio revisar dejarían el mínimo
        # a la altura de ese accidente, y los mínimos solo suben.
        evaluados = {r.nombre for r in resultados}
        saltados = [c.name for c in listar_casos(raiz) if c.name not in evaluados]
        fallidos = [r.nombre for r in resultados if r.fallo is not None]
        if saltados or fallidos:
            print("\nNo se fijan los mínimos: la medición no está completa.")
            if saltados:
                print(f"  · casos sin revisar, no evaluados: {', '.join(saltados)}")
            if fallidos:
                print(f"  · extracciones fallidas: {', '.join(fallidos)}")
            return 1
        ejecuciones.append(informe.totales)

    cobertura = _selector_total(selector)
    if cobertura is None:
        print("\nNo se fijan los mínimos: ningún caso tiene positivos.")
        return 1
    try:
        nuevos = minimos_desde(ejecuciones, cobertura)
    except ValueError as exc:
        print(
            f"\nNo se fijan los mínimos: {exc}. Hacen falta casos completos y casos "
            "parciales, los dos con hechos ciertos."
        )
        return 1

    previos = _leer_minimos(raiz) or {}
    bajan = [
        f"{clave}: {previos[clave]} → {valor}"
        for clave, valor in nuevos.items()
        if clave in previos and valor < previos[clave]
    ]
    if bajan:
        print("\nNo se escriben los mínimos: solo pueden subir, y estos bajarían:")
        for linea in bajan:
            print(f"  · {linea}")
        print(
            "Si la bajada es una decisión (otro modelo, casos nuevos más difíciles), "
            f"edita {NOMBRE_MINIMOS} a mano y explícalo en el commit."
        )
        return 1

    (raiz / NOMBRE_MINIMOS).write_text(
        json.dumps(
            {
                "medido_el": date.today().isoformat(),
                "model": model,
                "extraction_version": EXTRACTION_VERSION,
                "ejecuciones": EJECUCIONES_DE_BASE,
                "minimos": nuevos,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        # Sin esto, en Windows saldría con CRLF y el hook `mixed-line-ending`
        # tumbaría el commit de los mínimos.
        newline="\n",
    )
    print(f"\nMínimos escritos en {raiz / NOMBRE_MINIMOS}: {nuevos}")
    return 0


def _sin_casos() -> int:
    print(
        "No hay ningún caso evaluable. Captura y revisa pliegos primero "
        "(scripts/capturar_ficha_golden.py y scripts/revisar_ficha_golden.py; "
        "docs/plans/2026-10-eval-ficha-pliego.md §8).",
        file=sys.stderr,
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Eval de la ficha del pliego contra el golden, con el LLM real."
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="modelo con el que extraer")
    parser.add_argument("--caso", help="evaluar solo este caso")
    parser.add_argument("--raiz", type=Path, default=RAIZ_POR_DEFECTO)
    parser.add_argument("--salida", type=Path, help="escribir el resultado en este JSON")
    parser.add_argument(
        "--pendientes",
        action="store_true",
        help="dejar para revisión los hechos sin juzgar de los casos parciales",
    )
    parser.add_argument(
        "--check", action="store_true", help=f"devolver 1 por debajo de {NOMBRE_MINIMOS}"
    )
    parser.add_argument(
        "--fijar-minimos",
        action="store_true",
        help=f"{EJECUCIONES_DE_BASE} ejecuciones y escribir {NOMBRE_MINIMOS} (solo sube)",
    )
    args = parser.parse_args(argv)
    if args.fijar_minimos and args.caso:
        parser.error("--fijar-minimos mide todos los casos: no admite --caso")

    _sin_bd()

    if args.fijar_minimos:
        return _fijar_minimos(args.raiz, args.model)

    informe, resultados, selector = evaluar(args.raiz, model=args.model, solo=args.caso)
    if not resultados:
        return _sin_casos()
    print(f"Modelo: {args.model} · extractor: {EXTRACTION_VERSION}\n")
    print(formatear(informe, selector))
    for resultado in resultados:
        if resultado.fallo:
            print(f"\nFalló {resultado.nombre}: {resultado.fallo}")

    totales = _totales(informe, selector)
    if args.salida:
        _escribir_salida(args.salida, informe, resultados, totales, args.model)
    if args.pendientes:
        _escribir_pendientes(args.raiz, resultados)
    if not args.check:
        return 0

    minimos = _leer_minimos(args.raiz)
    if minimos is None:
        print(
            f"\n--check: no existe {NOMBRE_MINIMOS}. Fija la base con --fijar-minimos; "
            "sin mínimos no hay nada que comprobar, y eso no es un aprobado."
        )
        return 1
    # Un fichero al que le falta una clave no comprueba esa métrica, y eso no
    # puede salir como «se cumplen los mínimos».
    faltas = [
        f"{clave}: falta en {NOMBRE_MINIMOS}" for clave in CLAVES_DE_MINIMOS if clave not in minimos
    ]
    faltas += comprobar_minimos(totales, minimos)
    if faltas:
        print("\n--check: por debajo de los mínimos:")
        for falta in faltas:
            print(f"  · {falta}")
        return 1
    print("\n--check: se cumplen los mínimos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
