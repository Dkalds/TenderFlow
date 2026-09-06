"""Higiene del backlog: lo que dice la cabecera y lo que dice el árbol (C9.5).

`docs/IMPROVEMENT_BACKLOG.md` tiene dos capas que pueden contradecirse sin que
nada falle:

1. Las **tablas de cabecera** («Plan de arquitectura 2026-09», «Repaso del
   2026-08-27») marcan ítems como **Cerrado**.
2. Las secciones **P0-P3** contienen, por convención del propio documento,
   «solo ítems abiertos».

Un ítem marcado Cerrado arriba y todavía listado abajo es exactamente el estado
que hace que alguien lo trabaje dos veces. Y un ítem abierto que cita una
revisión Alembic que ya está en `db/alembic/versions/` probablemente esté hecho
y nadie lo movió.

Este script no cierra nada: avisa. Cerrar un ítem es una decisión, y moverlo a
_Cerrados_ con su fecha y su PR es trabajo de quien lo cerró.

Uso::

    python scripts/check_backlog_freshness.py            # informe
    python scripts/check_backlog_freshness.py --strict   # los avisos fallan

Exit 0 si no hay contradicciones duras; 1 si las hay.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKLOG = _REPO_ROOT / "docs" / "IMPROVEMENT_BACKLOG.md"
_VERSIONS = _REPO_ROOT / "db" / "alembic" / "versions"

#: Encabezado de un ítem: `### [P2] Título del ítem`.
_ITEM = re.compile(r"^###\s*\[(P[0-3])\]\s*(.+?)\s*$", re.M)
#: Fila de tabla de cabecera cuyo estado empieza por **Cerrado**.
_FILA_CERRADO = re.compile(r"^\|\s*(.+?)\s*\|\s*\*\*Cerrado\*\*", re.M)
#: Revisión Alembic citada en el cuerpo de un ítem (`v98`, `v112`…).
_REVISION = re.compile(r"\bv(\d{2,3})\b")

_SECCIONES_ABIERTAS = ("## P0", "## P1", "## P2", "## P3")
_SECCION_CERRADOS = "## Cerrados"


def _normaliza(texto: str) -> str:
    """Minúsculas, sin tildes, sin markup, para comparar títulos entre capas."""
    texto = re.sub(r"[`*_\[\]]", "", texto)
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^a-z0-9 ]+", " ", texto.lower())
    return " ".join(texto.split())


def _solape(a: str, b: str) -> float:
    """Proporción de palabras significativas de *a* presentes en *b*."""
    palabras_a = {p for p in _normaliza(a).split() if len(p) > 3}
    if not palabras_a:
        return 0.0
    palabras_b = {p for p in _normaliza(b).split() if len(p) > 3}
    return len(palabras_a & palabras_b) / len(palabras_a)


def _cuerpo_de_items(texto: str) -> list[tuple[str, str, str]]:
    """Devuelve `(prioridad, titulo, cuerpo)` de cada ítem de las secciones abiertas."""
    inicio = min(
        (texto.find(s) for s in _SECCIONES_ABIERTAS if texto.find(s) != -1),
        default=-1,
    )
    if inicio == -1:
        return []
    fin = texto.find(_SECCION_CERRADOS)
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
    texto = _BACKLOG.read_text(encoding="utf-8")

    cabecera_fin = min(
        (texto.find(s) for s in _SECCIONES_ABIERTAS if texto.find(s) != -1),
        default=len(texto),
    )
    cerrados_en_cabecera = [
        m.group(1) for m in _FILA_CERRADO.finditer(texto[:cabecera_fin])
    ]
    items = _cuerpo_de_items(texto)
    revisiones = _revisiones_presentes()

    errores: list[str] = []
    avisos: list[str] = []

    # 1. Contradicción dura: la cabecera lo da por cerrado y sigue en P0-P3.
    for prioridad, titulo, _cuerpo in items:
        for fila in cerrados_en_cabecera:
            if _solape(fila, titulo) >= 0.6:
                errores.append(
                    f"[{prioridad}] {titulo!r} sigue abierto, pero la cabecera lo marca "
                    f"**Cerrado** en la fila {fila!r}. Movelo a _Cerrados_ o corregí la fila."
                )
                break

    # 2. Aviso: cita una revisión Alembic que ya está en el árbol.
    for prioridad, titulo, cuerpo in items:
        citadas = {
            rev
            for rev in _REVISION.findall(cuerpo)
            if rev in revisiones
        }
        if citadas:
            avisos.append(
                f"[{prioridad}] {titulo!r} cita la/s revisión/es "
                f"{', '.join('v' + r for r in sorted(citadas))}, ya presentes en "
                f"db/alembic/versions/. ¿Sigue abierto?"
            )

    for a in avisos:
        print(f"WARN  {a}")
    for e in errores:
        print(f"ERROR {e}")

    if errores or (estricto and avisos):
        total = len(errores) + (len(avisos) if estricto else 0)
        print(f"\n{total} problema/s de frescura en el backlog.")
        return 1
    print(
        f"Backlog consistente: {len(items)} ítems abiertos, "
        f"{len(cerrados_en_cabecera)} marcados Cerrado en cabecera, "
        f"{len(avisos)} aviso/s."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
