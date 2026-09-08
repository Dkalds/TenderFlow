"""Marca el censo histórico de PSCP como fuera del universo de análisis (C4.1).

Desde 2026-09-06 el conector de PSCP no persiste avisos sin señal tecnológica
(D24). Este script atiende lo que ya está ingerido: medido contra producción ese
mismo día, **684.374 filas de PSCP de las que solo 3.117 traen `tecnologia`** —
un 0,46 %, y el 96,9 % del corpus entero de `licitaciones`. Ese es el conjunto
que ahoga al dataset del clasificador SAP: un modelo entrenado sobre él aprende
a decir «no» y acierta el 99,5 % de las veces sin discriminar nada.

**Marca, no purga.** Un `DELETE` sobre 680.000 filas destruye dato público que
alguien podría querer para una serie histórica, y D24 solo pide acotar el
universo. Marcarlas ``analysis_universe = 'pscp_censo'`` las saca de todo lo que
consulte el universo tecnológico —`licitaciones_canonicas`, el dataset de ML,
los agregados— sin perderlas.

El SQL vive en ``db/repositories/licitaciones.py`` (ADR-022); aquí quedan los
lotes, el dry-run y el delta, que es lo propio de un script de operación.

Uso::

    python scripts/backfill_pscp_censo.py            # dry-run, imprime el delta
    python scripts/backfill_pscp_censo.py --apply    # marca
    python scripts/backfill_pscp_censo.py --apply --batch 5000

El delta antes/después se imprime siempre: es la cifra que la PR tiene que
anotar, y medirla es parte del ítem.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from db.repositories.licitaciones import (  # noqa: E402
    UNIVERSO_CENSO,
    marcar_censo_de_fuente,
    medir_censo_de_fuente,
)
from observability.logging import get_logger  # noqa: E402

log = get_logger(__name__)

#: Fuente afectada. El id del conector, tal cual lo escribe `licitaciones.fuente`.
FUENTE = "pscp"


def _imprime(titulo: str, m: dict[str, int]) -> None:
    pct = (100.0 * m["con_tecnologia"] / m["total"]) if m["total"] else 0.0
    print(f"\n{titulo}")
    print(f"  filas de {FUENTE}:            {m['total']:>9,}")
    print(f"  con señal tecnológica:    {m['con_tecnologia']:>9,}  ({pct:.2f} %)")
    print(f"  sin señal tecnológica:    {m['sin_tecnologia']:>9,}")
    print(f"  ya marcadas como censo:   {m['ya_marcadas']:>9,}")


def marcar(*, batch: int) -> int:
    """Marca por lotes hasta que no queda nada. Devuelve el total marcado."""
    marcadas = 0
    while True:
        n = marcar_censo_de_fuente(FUENTE, batch=batch)
        if n <= 0:
            break
        marcadas += n
        log.info("backfill_pscp_censo_lote", marcadas=n, acumulado=marcadas)
        print(f"  … {marcadas:,} marcadas")
    return marcadas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Ejecuta el marcado")
    parser.add_argument("--batch", type=int, default=5_000, help="Filas por lote (default 5000)")
    args = parser.parse_args()

    antes = medir_censo_de_fuente(FUENTE)
    _imprime("ANTES", antes)

    if not args.apply:
        pendientes = antes["sin_tecnologia"] - antes["ya_marcadas"]
        print(
            f"\nDRY-RUN: se marcarían {pendientes:,} filas como `{UNIVERSO_CENSO}`."
            "\nEjecutá con --apply para aplicarlo."
        )
        return 0

    marcadas = marcar(batch=args.batch)
    despues = medir_censo_de_fuente(FUENTE)
    _imprime("DESPUÉS", despues)

    print(f"\nDelta: {marcadas:,} filas marcadas como `{UNIVERSO_CENSO}`.")
    print(
        "Anotá esta cifra en la PR y volvé a correr `make audit-truth-check` "
        "para el delta de la auditoría."
    )
    log.info("backfill_pscp_censo_done", marcadas=marcadas, **despues)
    return 0


if __name__ == "__main__":
    sys.exit(main())
