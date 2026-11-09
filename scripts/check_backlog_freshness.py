"""Higiene del backlog: un ítem abierto que ya tiene su migración en el árbol (C9.5).

`docs/IMPROVEMENT_BACKLOG.md` contiene, por convención del propio documento,
«solo ítems abiertos»: cerrar uno es borrarlo, y el rastro es el PR. Un ítem
abierto que cita una revisión Alembic que ya está en `db/alembic/versions/`
probablemente esté hecho y nadie lo borró, que es exactamente el estado que
hace que alguien lo trabaje dos veces.

Este script no cierra nada: avisa. Cerrar un ítem es una decisión, y borrarlo
con el PR que lo resolvió es trabajo de quien lo cerró.

Lo que sí falla siempre: un ítem sin su primera línea **Estado actual** (fecha
y clase `código|propietario|medir|mixto`), o con una nota de progreso de fecha
posterior a la de esa línea. Es lo que se lee para saber qué queda; sin ella, o
sin reescribirla al avanzar, quien lea el ítem tomará el Problema por el estado.

Uso::

    python scripts/check_backlog_freshness.py            # informe
    python scripts/check_backlog_freshness.py --strict   # los avisos fallan
    python scripts/check_backlog_freshness.py --estado   # qué queda de cada ítem

`--estado` (`make backlog-estado`) es la forma de leer el backlog para proponer
o planificar: título, clase y Estado actual, sin el resto del texto.

Exit 1 si falta o está desactualizado algún Estado actual, o con `--strict` y
avisos; 0 en el resto (y siempre con `--estado`).
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
#: Primera línea obligatoria de cada ítem: lo que queda hoy, con fecha y clase.
#: El «Problema» se queda en el día en que se abrió y leerlo como estado hizo
#: proponer como pendientes cosas hechas (AGENTS.md §0).
_ESTADO_ACTUAL = re.compile(
    r"^- \*\*Estado actual \((\d{4}-\d{2}-\d{2})\):\*\* `(código|propietario|medir|mixto)`"
    r"(?: — )?(.*)$",
    re.M,
)
#: Nota de progreso con fecha en su etiqueta: `- **Progreso (2026-11-03):**`,
#: `- *Estado (2026-10-17):*`, `**Medido 2026-10-24 (log…):**`. La fecha tiene
#: que estar dentro de la negrita o cursiva de apertura, no en la prosa.
_NOTA_CON_FECHA = re.compile(r"^\s*(?:-\s*)?\*{1,2}[^*\n]{0,60}?(\d{4}-\d{2}-\d{2})", re.M)
#: Ruta del repo citada entre comillas invertidas en el Estado actual
#: (`scripts/x.py`, `db/alembic/versions/v159_….py`, `docs/STATUS.md`). Una frase
#: falsa no se detecta, pero sí la que nombra un fichero que ya no está.
_RUTA_CITADA = re.compile(
    r"`((?:\.?[\w-]+/)+[\w.-]+\.(?:py|ts|tsx|md|yml|yaml|json|sql|toml|mjs|txt))`"
)


def _estado(cuerpo: str) -> tuple[str, str, str] | None:
    """`(fecha, clase, texto)` del Estado actual, si el ítem empieza por él."""
    m = _ESTADO_ACTUAL.match(cuerpo.strip())
    return (m.group(1), m.group(2), m.group(3).strip()) if m else None


def _errores_de_estado(items: list[tuple[str, str, str]]) -> list[str]:
    """Ítems sin Estado actual, o con una nota de progreso posterior a él.

    Lo segundo es el fallo que la línea vino a evitar, desplazado: alguien
    apunta progreso debajo y no reescribe el estado, que vuelve a mentir.
    """
    errores: list[str] = []
    for prioridad, titulo, cuerpo in items:
        estado = _estado(cuerpo)
        if estado is None:
            errores.append(
                f"[{prioridad}] {titulo!r} no empieza por «- **Estado actual (AAAA-MM-DD):** "
                "`código|propietario|medir|mixto`» (ver Convenciones del backlog)."
            )
            continue
        faltan = sorted(
            r for r in _RUTA_CITADA.findall(estado[2]) if not (_REPO_ROOT / r.rstrip("/")).exists()
        )
        if faltan:
            errores.append(
                f"[{prioridad}] {titulo!r}: su Estado actual cita {', '.join(faltan)}, "
                "que no existe en el repo. ¿Se movió, se renombró o ya no aplica?"
            )
        resto = cuerpo.strip().split("\n", 1)[1] if "\n" in cuerpo.strip() else ""
        posteriores = sorted(f for f in _NOTA_CON_FECHA.findall(resto) if f > estado[0])
        if posteriores:
            errores.append(
                f"[{prioridad}] {titulo!r}: su Estado actual es del {estado[0]} y tiene "
                f"una nota del {posteriores[-1]}. Reescribe el Estado actual con lo que "
                "queda hoy."
            )
    return errores


def resumen(items: list[tuple[str, str, str]]) -> str:
    """Lo que queda de cada ítem, sin el resto del texto (`make backlog-estado`)."""
    lineas: list[str] = []
    for prioridad, titulo, cuerpo in items:
        estado = _estado(cuerpo)
        clase, texto = (estado[1], estado[2]) if estado else ("SIN ESTADO", "")
        lineas.append(f"[{prioridad}] `{clase}` {titulo}\n    {texto}")
    return "\n".join(lineas)


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
    # En Windows, stdout redirigido o en tubería (make, Git Bash) es cp1252, sin «≥».
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    estricto = "--strict" in sys.argv
    items = _cuerpo_de_items(_BACKLOG.read_text(encoding="utf-8"))
    if "--estado" in sys.argv:
        print(resumen(items))
        return 0
    revisiones = _revisiones_presentes()

    errores = _errores_de_estado(items)
    for e in errores:
        print(f"ERROR {e}")

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

    if errores:
        print(f"\n{len(errores)} ítem/s sin «Estado actual» o con él desactualizado.")
        return 1
    if estricto and avisos:
        print(f"\n{len(avisos)} problema/s de frescura en el backlog.")
        return 1
    print(f"Backlog consistente: {len(items)} ítems abiertos, {len(avisos)} aviso/s.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
