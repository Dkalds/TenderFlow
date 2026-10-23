"""Mide cuántas canónicas cambian de fila (y de URL) con la revisión ``v156``.

``v156`` cambia el primer criterio de canónica de ``licitaciones_canonicas``: de
``fuente <> 'placsp'`` a PLACSP (con ``bulk_YYYYMM``) → resto → TED. Antes de
aplicarla en producción (``migrate.yml``), el propietario revisa con esto qué
contratos cambian de fila representante. Solo lee: no toca la vista ni la
tabla, y responde lo mismo antes y después de aplicar la revisión.

Uso::

    ENV=dev python scripts/medir_delta_canonicas.py            # resumen + 20 ejemplos
    ENV=dev python scripts/medir_delta_canonicas.py --todos    # todos los cambios
    ENV=dev python scripts/medir_delta_canonicas.py --json > delta.json

Requiere ``DATABASE_URL`` apuntando a la base que se va a migrar.

Cómo leer el resultado: ``ted → bulk_202606`` es un contrato que la vista
publicaba por su aviso del DOUE y pasará a publicar por su fila de PLACSP.
``placsp → bulk_*`` aparece cuando las dos filas son de PLACSP: antes ganaba la
del ATOM por llamarse ``placsp``; ahora, como iguales, la publicada antes. La
URL vieja no da 404: la fila que deja de ser canónica sigue teniendo ficha.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from db.repositories.canonicas_delta import DeltaCanonicas, medir_delta  # noqa: E402


def render_texto(delta: DeltaCanonicas, *, limite: int | None) -> str:
    """Resumen legible. Toma el resultado ya medido para que el test no necesite BD."""
    n = len(delta.cambios)
    pct = 100.0 * n / delta.contratos if delta.contratos else 0.0
    out = [
        f"Contratos publicables: {delta.contratos}",
        f"Cambian de fila canónica: {n} ({pct:.2f} %)",
    ]
    if n:
        out.append("")
        out.append("Por transición (fuente antes → después):")
        out.extend(f"  {k}: {v}" for k, v in delta.por_transicion().items())
        muestra = delta.cambios if limite is None else delta.cambios[:limite]
        out.append("")
        out.append(f"Ejemplos ({len(muestra)} de {n}): antes → después")
        out.extend(
            f"  {c.antes} [{c.fuente_antes}] → {c.despues} [{c.fuente_despues}]" for c in muestra
        )
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--json", action="store_true", help="salida JSON completa")
    parser.add_argument("--todos", action="store_true", help="lista todos los cambios")
    args = parser.parse_args(argv)

    delta = medir_delta()
    if args.json:
        print(
            json.dumps(
                {
                    "contratos": delta.contratos,
                    "cambian": len(delta.cambios),
                    "por_transicion": delta.por_transicion(),
                    "cambios": [asdict(c) for c in delta.cambios],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(render_texto(delta, limite=None if args.todos else 20))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
