"""Presupuesto de First Load JS por ruta, como ratchet (C7.6).

Qué mide
--------
El **First Load JS** de cada ruta del App Router: los bytes de JavaScript que el
navegador descarga y ejecuta antes de que la página sea interactiva. Es la cifra
que gobierna el LCP y el INP en un móvil con red lenta, y hasta hoy nadie la
vigilaba — `@next/bundle-analyzer` ni siquiera estaba instalado (hecho 25 del
plan) pese a que S5.6 del plan de septiembre lo pedía.

De dónde sale el número
-----------------------
De `web/.next/diagnostics/route-bundle-stats.json`, que **la propia build
escribe** con `firstLoadUncompressedJsBytes` por ruta. No de la tabla que
`next build` imprime: esa es salida humana, cambia de formato entre versiones y
parsearla ataría el control a una. Y no recalculándolo sumando chunks a mano:
Next ya resuelve qué chunks comparten dos rutas, y repetir esa aritmética aquí
sería mantener una segunda definición de «First Load» que puede discrepar de la
que el servidor aplica.

Es **sin comprimir**. Lo que viaja por la red va con gzip/brotli, así que el
número absoluto es mayor que el que ve el usuario; como techo relativo eso da
igual —lo que se vigila es que no suba— y tiene la ventaja de no depender del
nivel de compresión del CDN, que no controlamos.

Por qué un ratchet y no un umbral fijo
--------------------------------------
Un umbral fijo se elige una vez, se queda grande y deja de morder. El techo de
`web/bundle-budget.json` es el tamaño **medido**, y `--update` solo lo baja: una
ruta que adelgaza fija el techo nuevo, una que engorda falla. Es el mismo patrón
que `check_inline_styles.py` y `check_title_attrs.py`.

Uso::

    cd web && npm run build          # escribe .next/diagnostics/
    python scripts/check_bundle_budget.py
    python scripts/check_bundle_budget.py --update   # baja los techos medidos
    ANALYZE=true npm run build       # informes de @next/bundle-analyzer

``--update`` **solo baja**, así que no sirve para deshacer un techo editado a
mano por debajo de lo real: para rehacer el fichero desde la medición hay que
borrarlo y volver a correrlo. Esa asimetría es la que hace que el ratchet sea un
ratchet — si `--update` subiera, cualquier regresión se «arreglaría» corriéndolo.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEB = _REPO_ROOT / "web"
_STATS = _WEB / ".next" / "diagnostics" / "route-bundle-stats.json"
_PRESUPUESTO = _WEB / "bundle-budget.json"

#: Margen sobre el valor medido al fijar un techo nuevo.
#:
#: 3 % absorbe el ruido entre builds (orden de módulos, nombres con hash) sin
#: dejar sitio a una regresión real: 3 % de una ruta de 1,5 MB son 45 KB, y una
#: librería nueva pesa más que eso.
MARGEN = 0.03


def medir() -> dict[str, int]:
    """`{ruta: bytes de First Load JS}` según la última build."""
    if not _STATS.exists():
        raise SystemExit(
            f"No existe {_STATS.relative_to(_REPO_ROOT).as_posix()}. "
            "Corré `cd web && npm run build` antes."
        )
    filas = json.loads(_STATS.read_text(encoding="utf-8"))
    return {
        str(f["route"]): int(f["firstLoadUncompressedJsBytes"])
        for f in filas
        if f.get("firstLoadUncompressedJsBytes") is not None
    }


def _cargar_presupuesto() -> dict[str, int]:
    if not _PRESUPUESTO.exists():
        return {}
    datos = json.loads(_PRESUPUESTO.read_text(encoding="utf-8"))
    return {k: int(v) for k, v in datos.get("rutas", {}).items()}


def _guardar_presupuesto(techos: dict[str, int]) -> None:
    _PRESUPUESTO.write_text(
        json.dumps(
            {
                "_comentario": (
                    "First Load JS por ruta, en bytes sin comprimir. Lo genera "
                    "`python scripts/check_bundle_budget.py --update` desde "
                    ".next/diagnostics/route-bundle-stats.json y SOLO PUEDE BAJAR: subir "
                    "un techo es aceptar una regresión de rendimiento, y eso se decide a "
                    "propósito, no de pasada."
                ),
                "rutas": dict(sorted(techos.items())),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update",
        action="store_true",
        help="Baja los techos a lo medido (nunca los sube) y guarda el fichero.",
    )
    args = parser.parse_args(argv)

    medido = medir()
    techos = _cargar_presupuesto()

    if args.update:
        nuevos = dict(techos)
        bajados = 0
        for ruta, bytes_ in medido.items():
            techo_nuevo = int(bytes_ * (1 + MARGEN))
            anterior = nuevos.get(ruta)
            if anterior is None or techo_nuevo < anterior:
                nuevos[ruta] = techo_nuevo
                bajados += anterior is not None
        # Una ruta que desaparece sale del presupuesto: conservar su techo
        # dejaría un número que ya no mide nada y que nadie sabría retirar.
        nuevos = {r: v for r, v in nuevos.items() if r in medido}
        _guardar_presupuesto(nuevos)
        print(f"Presupuesto actualizado: {len(nuevos)} rutas, {bajados} techo/s bajado/s.")
        return 0

    if not techos:
        print(
            "No hay presupuesto todavía. Generalo con "
            "`python scripts/check_bundle_budget.py --update` tras una build.",
            file=sys.stderr,
        )
        return 1

    excesos: list[str] = []
    for ruta, bytes_ in sorted(medido.items()):
        techo = techos.get(ruta)
        if techo is None:
            # Una ruta nueva no falla: no tiene con qué compararse. Entra en el
            # presupuesto en el siguiente `--update`.
            print(f"NUEVA  {ruta}: {bytes_ / 1024:.0f} KB (sin techo aún)")
            continue
        if bytes_ > techo:
            excesos.append(
                f"{ruta}: {bytes_ / 1024:.0f} KB > techo {techo / 1024:.0f} KB "
                f"(+{(bytes_ - techo) / 1024:.0f} KB)"
            )

    for e in excesos:
        print(f"ERROR  {e}", file=sys.stderr)
    print(f"Presupuesto de bundle: {len(medido)} rutas medidas, {len(excesos)} por encima.")
    return 1 if excesos else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
