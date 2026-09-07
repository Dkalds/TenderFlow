"""Cobertura de una fuente autonómica contra una muestra de referencia (C4.3).

Qué mide
--------
Cuántos expedientes de una muestra **verificada contra la fuente** vuelve a
encontrar el conector. Es la aceptación de C4.3 —«cobertura ≥ 90 % contra una
muestra de cincuenta expedientes por fuente»— convertida en un número que
alguien puede volver a sacar, en vez de una afirmación.

Qué NO mide
-----------
Que la fuente publique todo lo que existe. Eso no es medible desde fuera: haría
falta un censo independiente del sector público vasco. Esto mide **fidelidad del
conector**: dado lo que la fuente publica, cuánto llega.

La muestra
----------
``tests/fixtures/euskadi/muestra_cobertura.json``: 50 anuncios tomados al azar
con semilla fija del buscador oficial y **verificados uno a uno abriendo su
ficha pública** y comprobando que muestra el mismo número de expediente. Esa
verificación es lo que la separa de «la salida del conector comparada consigo
misma»: si el conector cambiara de criterio, la muestra no se movería.

Uno de los cincuenta no lleva expediente en la fuente (medido: el campo está en
el 99 % de los avisos); queda en la muestra marcado, porque su ficha sí existe.

La ventana
----------
El conector recorre de más nuevo a más viejo con un tope de páginas, así que a
medida que la muestra envejece deja de caber en el recorrido. El informe separa
las dos cosas: cuántos de la muestra caían **dentro** de la ventana recorrida y
cuántos de ésos aparecieron. Una cobertura del 100 % sobre 12 de 50 dice que la
muestra hay que refrescarla, no que el conector empeoró.

Uso
---
    python scripts/check_regional_coverage.py                 # euskadi, 30 páginas
    python scripts/check_regional_coverage.py --paginas 120   # alcanza más atrás
    python scripts/check_regional_coverage.py --min 90        # falla por debajo

Sale a la red: **no** es parte de la suite unitaria. Se ejecuta a mano o desde
un job programado, como el resto de los chequeos que hablan con una fuente real.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_RAIZ = Path(__file__).resolve().parents[1]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

MUESTRAS = {"euskadi": _RAIZ / "tests" / "fixtures" / "euskadi" / "muestra_cobertura.json"}

#: Umbral de aceptación de C4.3.
MIN_COBERTURA_PCT = 90.0
#: Páginas a recorrer por defecto: 30 paginas de 50 = 1.500 avisos ≈ dos semanas de flujo.
PAGINAS_POR_DEFECTO = 30


def _cargar_muestra(fuente: str) -> dict[str, Any]:
    ruta = MUESTRAS.get(fuente)
    if ruta is None:
        raise SystemExit(f"No hay muestra registrada para '{fuente}'. Hay: {sorted(MUESTRAS)}")
    if not ruta.exists():
        raise SystemExit(f"Falta la muestra {ruta}")
    datos: dict[str, Any] = json.loads(ruta.read_text(encoding="utf-8"))
    return datos


def _recorrer(fuente: str, paginas: int) -> tuple[dict[str, str | None], int | None]:
    """``{content_name: fecha}`` de todo lo que el conector emite, y el total declarado."""
    if fuente != "euskadi":  # pragma: no cover - hoy solo hay una fuente con muestra
        raise SystemExit(f"Fuente sin recorrido implementado: {fuente}")
    from scraper.connectors.euskadi import EuskadiApiConnector

    conector = EuskadiApiConnector(max_paginas=paginas)
    vistos = {
        aviso.natural_id: (str(aviso.payload.get("publicado") or "") or None)
        for aviso in conector.fetch(None)
    }
    return vistos, conector.total_declarado


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--fuente", default="euskadi", choices=sorted(MUESTRAS))
    parser.add_argument("--paginas", type=int, default=PAGINAS_POR_DEFECTO)
    parser.add_argument(
        "--min",
        type=float,
        default=MIN_COBERTURA_PCT,
        help="Cobertura mínima exigida sobre la parte de la muestra alcanzada",
    )
    args = parser.parse_args(argv)

    muestra = _cargar_muestra(args.fuente)
    esperados = [m["content_name"] for m in muestra["expedientes"]]
    vistos, total_declarado = _recorrer(args.fuente, args.paginas)

    fechas = sorted(f for f in vistos.values() if f)
    ventana = (fechas[0], fechas[-1]) if fechas else (None, None)

    encontrados = [c for c in esperados if c in vistos]
    # Alcanzables: los de la muestra que caen en la ventana recorrida. Un
    # expediente publicado antes del corte no es una pérdida del conector.
    faltan = [c for c in esperados if c not in vistos]

    print(f"\n─── Cobertura de '{args.fuente}' ───")
    print(f"  Muestra          : {len(esperados)} anuncios ({muestra['capturada']})")
    print(f"  Páginas          : {args.paginas}")
    print(f"  Avisos recorridos: {len(vistos)}")
    if ventana[0]:
        print(f"  Ventana          : {ventana[0]} .. {ventana[1]}")
    if total_declarado:
        print(f"  La fuente declara: {total_declarado:,} resultados")

    alcanzables = len(esperados)
    if ventana[0]:
        # Fuera de ventana = publicados antes del más viejo que se llegó a leer.
        # Sin fecha en la muestra no se puede decidir, así que cuentan como
        # alcanzables: el sesgo va en contra del conector, no a su favor.
        fuera = [
            m["content_name"]
            for m in muestra["expedientes"]
            if m.get("publicado") and str(m["publicado"]) < ventana[0]
        ]
        alcanzables = len(esperados) - len(fuera)
        if fuera:
            print(f"  Fuera de ventana : {len(fuera)} (publicados antes de {ventana[0]})")

    pct = 100.0 * len(encontrados) / alcanzables if alcanzables else 0.0
    print(f"\n  Encontrados      : {len(encontrados)}/{alcanzables}  ({pct:.1f} %)")
    if faltan:
        print(f"  No encontrados   : {', '.join(faltan[:10])}")

    if alcanzables == 0:
        print("\n[AVISO] La muestra quedó fuera de la ventana: refrescala o subí --paginas.")
        return 0
    if pct + 1e-9 < args.min:
        print(f"\n[ERROR] Cobertura {pct:.1f} % por debajo del mínimo exigido ({args.min:.0f} %).")
        return 1
    print(f"\n[OK] Cobertura {pct:.1f} % ≥ {args.min:.0f} %.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
