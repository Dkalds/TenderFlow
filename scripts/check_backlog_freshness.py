"""Higiene del backlog: un ítem abierto que ya tiene su migración en el árbol (C9.5).

`docs/IMPROVEMENT_BACKLOG.md` contiene, por convención del propio documento,
«solo ítems abiertos»: cerrar uno es borrarlo, y el rastro es el PR. Un ítem
abierto que cita una revisión Alembic que ya está en `db/alembic/versions/`
probablemente esté hecho y nadie lo borró, que es exactamente el estado que
hace que alguien lo trabaje dos veces.

Este script no cierra nada: avisa. Cerrar un ítem es una decisión, y borrarlo
con el PR que lo resolvió es trabajo de quien lo cerró.

Uso::

    python scripts/check_backlog_freshness.py            # informe
    python scripts/check_backlog_freshness.py --strict   # los avisos fallan

Exit 0 salvo con `--strict` y avisos.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKLOG = _REPO_ROOT / "docs" / "IMPROVEMENT_BACKLOG.md"
_VERSIONS = _REPO_ROOT / "db" / "alembic" / "versions"

#: Encabezado de un ítem: `### [P2] Título del ítem`.
_ITEM = re.compile(r"^###\s*\[(P[0-3])\]\s*(.+?)\s*$", re.M)
#: Revisión Alembic citada en el cuerpo de un ítem (`v98`, `v112`…).
_REVISION = re.compile(r"\bv(\d{2,3})\b")

_SECCIONES_ABIERTAS = ("## P0", "## P1", "## P2", "## P3")
#: Tras los ítems solo queda la plantilla, cuyo `### [P0|P1|…]` no es un ítem.
_FIN_DE_ITEMS = "## Plantilla nueva entrada"


def _cuerpo_de_items(texto: str) -> list[tuple[str, str, str]]:
    """Devuelve `(prioridad, titulo, cuerpo)` de cada ítem de las secciones abiertas."""
    inicio = min(
        (texto.find(s) for s in _SECCIONES_ABIERTAS if texto.find(s) != -1),
        default=-1,
    )
    if inicio == -1:
        return []
    fin = texto.find(_FIN_DE_ITEMS)
    region = texto[inicio : fin if fin != -1 else len(texto)]

    items: list[tuple[str, str, str]] = []
    marcas = list(_ITEM.finditer(region))
    for i, m in enumerate(marcas):
        final = marcas[i + 1].start() if i + 1 < len(marcas) else len(region)
        items.append((m.group(1), m.group(2), region[m.end() : final]))
    return items


def _revisiones_presentes() -> set[str]:
    return {
        m.group(1)
        for f in _VERSIONS.glob("v*.py")
        if (m := re.match(r"^v(\d+)_", f.name)) is not None
    }


def main() -> int:
    estricto = "--strict" in sys.argv
    items = _cuerpo_de_items(_BACKLOG.read_text(encoding="utf-8"))
    revisiones = _revisiones_presentes()

    avisos: list[str] = []
    for prioridad, titulo, cuerpo in items:
        citadas = {rev for rev in _REVISION.findall(cuerpo) if rev in revisiones}
        if citadas:
            avisos.append(
                f"[{prioridad}] {titulo!r} cita la/s revisión/es "
                f"{', '.join('v' + r for r in sorted(citadas))}, ya presentes en "
                f"db/alembic/versions/. ¿Sigue abierto?"
            )

    for a in avisos:
        print(f"WARN  {a}")

    if estricto and avisos:
        print(f"\n{len(avisos)} problema/s de frescura en el backlog.")
        return 1
    print(f"Backlog consistente: {len(items)} ítems abiertos, {len(avisos)} aviso/s.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
