"""Mide la cobertura de ``procedimiento``, ``tramitacion`` y ``peso_precio_pct``.

Las tres columnas se persisten desde v85 pero siguen fuera de
``FEATURE_COLUMNS`` del modelo de baja: el criterio las admite solo con
cobertura real por encima del 50 % (``services.ml.features.
FEATURES_PENDIENTES_COBERTURA`` y el P3 del backlog «Medir la cobertura…»).
Este script es esa medición, para que no haya que reescribir la query cada vez.

Uso::

    ENV=dev python scripts/medir_cobertura_features.py            # Markdown
    ENV=dev python scripts/medir_cobertura_features.py --json     # para archivar

Requiere ``DATABASE_URL`` (pool de lectura; nunca escribe). El SQL vive en
``db.repositories.ml_dataset.MlDatasetRepository.cobertura_features_pendientes``.

Cómo leer el resultado
----------------------
- **dataset_baja** es la población que decide: las filas con las que entrena
  el modelo, con la misma regla de denominador y de fechas.
- **universo_abierto** es lo que puntúa el batch. Si una feature está cubierta
  en el dataset y vacía aquí, entrenarla no sirve.
- Las filas **por fuente** y **por año** explican un total bajo: el parser solo
  lee los tres campos del CODICE de PLACSP y desde el 2026-08-18. Un año viejo
  al 0 % es histórico sin reprocesar, no ausencia en la fuente.
- La columna ``≥ 50 %`` marca el umbral del criterio **solo sobre el total del
  dataset**; los cortes son diagnóstico, no decisión.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

#: Umbral del criterio de aceptación (backlog P3, ``FEATURES_PENDIENTES_COBERTURA``).
UMBRAL_COBERTURA_PCT = 50.0

CAMPOS: tuple[str, ...] = ("procedimiento", "tramitacion", "peso_precio_pct")


def _pct(parte: int, total: int) -> float | None:
    return round(100.0 * parte / total, 1) if total else None


def con_porcentajes(filas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Añade ``<campo>_pct`` a cada fila. Toma dicts para testear sin BD."""
    salida: list[dict[str, Any]] = []
    for fila in filas:
        n = int(fila.get("n") or 0)
        extra = {f"{campo}_pct": _pct(int(fila.get(campo) or 0), n) for campo in CAMPOS}
        salida.append({**fila, **extra})
    return salida


def _corte(fila: dict[str, Any]) -> str:
    if fila.get("por_fuente"):
        return f"fuente={fila.get('fuente') or '∅'}"
    if fila.get("por_anio"):
        return f"año={fila.get('anio') or '∅'}"
    return "**total**"


def _celda(pct: float | None) -> str:
    return "—" if pct is None else f"{pct} %"


def render_markdown(filas: list[dict[str, Any]]) -> str:
    """Informe en Markdown sobre filas ya con porcentajes."""
    out = ["# Cobertura de las features pendientes del modelo de baja", ""]
    out.append("| Población | Corte | Filas | " + " | ".join(CAMPOS) + " |")
    out.append("|---|---|---:|" + "---:|" * len(CAMPOS))
    for fila in filas:
        celdas = " | ".join(_celda(fila.get(f"{campo}_pct")) for campo in CAMPOS)
        out.append(f"| {fila['poblacion']} | {_corte(fila)} | {fila['n']} | {celdas} |")

    total = next(
        (
            f
            for f in filas
            if f["poblacion"] == "dataset_baja"
            and not f.get("por_fuente")
            and not f.get("por_anio")
        ),
        None,
    )
    out.append("")
    if total is None or not total.get("n"):
        out.append("Veredicto: **sin filas en el dataset de baja**; no hay nada que decidir.")
    else:
        out.append(f"Veredicto sobre el total del dataset (umbral {UMBRAL_COBERTURA_PCT:g} %):")
        out.append("")
        for campo in CAMPOS:
            pct = total.get(f"{campo}_pct")
            supera = pct is not None and pct >= UMBRAL_COBERTURA_PCT
            out.append(f"- `{campo}`: {_celda(pct)} — {'supera' if supera else 'no supera'}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", maxsplit=1)[0])
    parser.add_argument("--json", action="store_true", help="Salida JSON en vez de Markdown")
    args = parser.parse_args(argv)

    from db.repositories.ml_dataset import MlDatasetRepository

    filas = con_porcentajes(MlDatasetRepository().cobertura_features_pendientes())
    if args.json:
        print(json.dumps(filas, ensure_ascii=False, indent=2, default=str))
    else:
        print(render_markdown(filas))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
