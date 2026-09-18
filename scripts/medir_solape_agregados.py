"""Mide cuánto de la contratación TI autonómica llega ya a PLACSP (D16).

D16 (2026-09-06) dejó fuera de alcance los portales de Madrid, Andalucía y la
Comunidad Valenciana «hasta petición escrita de un cliente». La revisión de
salida al mercado del 2026-09-13 pidió, antes de escribir un conector, medir
el solape: qué parte de los expedientes TI de esas comunidades entra ya por
los avisos agregados de PLACSP (``estado = 'AGR'``) o por publicación directa.
Este script es esa medición. **No cambia D16**: da el número con el que se
vuelve a decidir.

Uso::

    make medir-solape                       # últimos 12 meses, tres CCAA de D16
    python scripts/medir_solape_agregados.py --meses 24 --ccaa Madrid --ccaa Aragón
    python scripts/medir_solape_agregados.py --desde 2025-01-01 --json > solape.json

Requiere ``DATABASE_URL`` (se lee con el pool de lectura, nunca escribe).

Cómo leer el resultado
----------------------
- **universo TI**: filas que cumplen el mismo predicado que la superficie
  pública y la analítica (``universo_tecnologico_sql``). Es el denominador.
- **agregados**: de ese universo, cuántas llegaron como aviso agregado. Un
  porcentaje alto en una CCAA sin conector propio significa que su portal ya
  vierte en PLACSP y un conector aportaría poco; uno bajo con muchos órganos
  ausentes de la lista es la señal contraria.
- **por fuente**: qué conector trajo cada fila. ``placsp`` con estado ``AGR``
  es agregación; ``placsp`` con otro estado es publicación directa.
- **órganos**: los quince con más expedientes TI de cada CCAA de interés, con
  su mezcla de fuentes. Un ayuntamiento grande que no aparece es un hueco de
  cobertura que ninguna cifra agregada enseña.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from db.repositories.cobertura import organos_por_fuente, solape_por_ccaa  # noqa: E402

#: Las tres comunidades que D16 declaró fuera de alcance con nombre propio.
CCAA_D16: tuple[str, ...] = ("Madrid", "Andalucía", "Comunidad Valenciana")


def _fecha_desde(args: argparse.Namespace) -> date:
    if args.desde:
        return date.fromisoformat(args.desde)
    return (datetime.now(UTC) - timedelta(days=30 * int(args.meses))).date()


def _fmt_fuentes(fuentes: dict[str, int]) -> str:
    return ", ".join(f"{k} {v}" for k, v in fuentes.items()) or "—"


def render_markdown(
    *, desde: date, filas: list[dict[str, Any]], organos: dict[str, list[dict[str, Any]]]
) -> str:
    """Informe en Markdown. Toma dicts para que el test no dependa de la BD."""
    out: list[str] = []
    out.append(f"# Solape de fuentes por CCAA (desde {desde.isoformat()})")
    out.append("")
    out.append(
        "| CCAA | Expedientes | Universo TI | Agregados (AGR) | % agregados | Por fuente (TI) |"
    )
    out.append("|---|---:|---:|---:|---:|---|")
    for f in filas:
        pct = f.get("pct_agregados")
        pct_txt = "—" if pct is None else f"{pct} %"
        out.append(
            f"| {f['ccaa']} | {f['total']} | {f['universo_ti']} | {f['universo_ti_agregados']} "
            f"| {pct_txt} | {_fmt_fuentes(dict(f['universo_ti_por_fuente']))} |"
        )
    for ccaa, lista in organos.items():
        out.append("")
        out.append(f"## {ccaa}: órganos con más expedientes TI")
        out.append("")
        if not lista:
            out.append("_Sin expedientes TI en la ventana._")
            continue
        out.append("| Órgano | Expedientes TI | Por fuente |")
        out.append("|---|---:|---|")
        for o in lista:
            out.append(
                f"| {o['organo']} | {o['expedientes']} | {_fmt_fuentes(dict(o['fuentes']))} |"
            )
    out.append("")
    out.append(
        "Lectura: un porcentaje alto de agregados en una CCAA sin conector propio "
        "significa que su portal ya vierte en PLACSP. D16 se revisa con este número, "
        "no con una intuición (docs/regional-source-coverage.md)."
    )
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", maxsplit=1)[0])
    parser.add_argument(
        "--desde", help="Fecha ISO de inicio de la ventana (prevalece sobre --meses)"
    )
    parser.add_argument("--meses", type=int, default=12, help="Ventana en meses (por defecto 12)")
    parser.add_argument(
        "--ccaa",
        action="append",
        help="CCAA para el detalle de órganos; repetible. Por defecto las tres de D16.",
    )
    parser.add_argument("--top", type=int, default=15, help="Órganos por CCAA en el detalle")
    parser.add_argument("--json", action="store_true", help="Salida JSON en vez de Markdown")
    args = parser.parse_args(argv)

    desde = _fecha_desde(args)
    ccaa_detalle = tuple(args.ccaa) if args.ccaa else CCAA_D16

    filas = [{**asdict(f), "pct_agregados": f.pct_agregados} for f in solape_por_ccaa(desde=desde)]
    organos = {
        ccaa: [asdict(o) for o in organos_por_fuente(ccaa=ccaa, desde=desde, limit=args.top)]
        for ccaa in ccaa_detalle
    }

    if args.json:
        print(
            json.dumps(
                {"desde": desde.isoformat(), "ccaa": filas, "organos": organos},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(render_markdown(desde=desde, filas=filas, organos=organos))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
