#!/usr/bin/env python3
"""Ratchet de superficie: una operación nueva de la API se justifica por escrito.

AGENTS.md §0 pide, antes de añadir una superficie, comprobar que ninguna
existente cubre ya el caso. Era una frase: la API pasó de 154 operaciones
(2026-08-07, el día que se declaró el congelamiento) a 292 (2026-10-10) sin que
nada preguntara por qué hacía falta cada una. Este gate convierte la frase en
un paso del cambio.

Cómo funciona
-------------

* ``api/superficie_congelada.txt`` es la línea base: las operaciones que
  existían al escribir el gate, una por línea (``MÉTODO /ruta``). **No se le
  añaden líneas.** Cuando una operación se retira, su línea se borra y la base
  encoge: es la medida de cuánta superficie heredada queda.
* ``NUEVAS`` (aquí abajo) es el único camino para añadir una operación: su
  clave y un motivo que diga **qué superficie existente se miró y por qué no
  alcanza**. Un motivo vacío o de compromiso falla.
* Una operación que no está en ninguna de las dos falla. Una entrada de
  cualquiera de las dos que ya no existe en la app también: las listas tienen
  que describir la API real.

No es un congelamiento: añadir un endpoint cuesta una línea. Lo que impide es
añadirlo sin haberse hecho la pregunta.

La superficie se lee de ``app.routes`` con ``ENV=dev`` y ``APP_PROFILE=api``,
igual que ``scripts/gen_status.py``: en ``dev`` existe ``/auth/dev-login``, y el
perfil ``worker`` solo monta ``health``. Con otro entorno la lista sería otra.

Uso::

    ENV=dev python scripts/check_api_surface.py           # el gate
    ENV=dev python scripts/check_api_surface.py --list    # operaciones de hoy
    ENV=dev python scripts/check_api_surface.py --count   # solo el número
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_BASE = _ROOT / "api" / "superficie_congelada.txt"

#: Un motivo más corto que esto no puede nombrar una superficie y decir por qué
#: no alcanza. No mide la calidad del motivo —eso es de la revisión—, solo
#: impide el ``"hace falta"``.
MOTIVO_MINIMO = 40

# ── Operaciones añadidas después de la línea base ───────────────────────────
# Formato: ``"MÉTODO /ruta": "qué superficie existente se miró y por qué no
# alcanza"``. Una por línea, en orden alfabético de ruta, para que dos ramas
# que añaden operaciones distintas no choquen al fusionar.
NUEVAS: dict[str, str] = {
    "POST /api/v1/me/profile/preview": (
        "Se miró GET /analytics/scoring, que puntúa siempre con el perfil guardado: "
        "no admite uno de prueba, y unos pesos con sus palabras clave y CPV no caben "
        "en una query. PUT /me/profile lo aceptaría, pero guardándolo. La vista previa "
        "necesita además las dos pasadas (prueba y guardado) sobre el mismo universo "
        "en una sola respuesta, para poder decir cuánto se mueve cada oportunidad."
    ),
}


def leer_base(ruta: Path = _BASE) -> set[str]:
    """Operaciones de la línea base. Ignora líneas vacías y comentarios ``#``."""
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    return {s for linea in lineas if (s := linea.strip()) and not s.startswith("#")}


def operaciones() -> list[str]:
    """Operaciones que expone la app hoy, como ``"MÉTODO /ruta"``.

    Reusa el recorrido de ``scripts/gen_status.py`` para que ``docs/STATUS.md``
    y este gate no puedan contar dos superficies distintas.
    """
    for carpeta in (_ROOT, _ROOT / "scripts"):
        if str(carpeta) not in sys.path:
            sys.path.insert(0, str(carpeta))
    import gen_status

    return sorted(f"{metodo} {ruta}" for metodo, ruta in gen_status._endpoints())


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="imprime las operaciones actuales")
    parser.add_argument("--count", action="store_true", help="imprime solo el conteo")
    args = parser.parse_args(argv)

    actuales = set(operaciones())

    if args.count:
        print(len(actuales))
        return 0
    if args.list:
        print("\n".join(sorted(actuales)))
        return 0

    base = leer_base()
    sin_justificar = sorted(actuales - base - set(NUEVAS))
    fosiles_base = sorted(base - actuales)
    fosiles_nuevas = sorted(set(NUEVAS) - actuales)
    duplicadas = sorted(set(NUEVAS) & base)
    motivos_cortos = sorted(
        op for op, motivo in NUEVAS.items() if len(motivo.strip()) < MOTIVO_MINIMO
    )

    if sin_justificar:
        print(
            f"{len(sin_justificar)} operación(es) NUEVA(s) sin justificar:",
            file=sys.stderr,
        )
        for op in sin_justificar:
            print(f"  - {op}", file=sys.stderr)
        print(
            "\nAGENTS.md §0: antes de añadir una superficie, comprobá que ninguna "
            "existente cubre ya el caso (un filtro más, un campo más en un DTO, "
            "otra vista del mismo recurso). Si de verdad hace falta, añadí la "
            "operación a NUEVAS en scripts/check_api_surface.py con el motivo: qué "
            "superficie miraste y por qué no alcanza. La línea base "
            "(api/superficie_congelada.txt) no admite líneas nuevas.",
            file=sys.stderr,
        )
    if fosiles_base:
        print(
            f"\n{len(fosiles_base)} línea(s) de api/superficie_congelada.txt ya no "
            "existen en la app: bórralas, la base solo puede encoger.",
            file=sys.stderr,
        )
        for op in fosiles_base:
            print(f"  - {op}", file=sys.stderr)
    if fosiles_nuevas:
        print(
            f"\n{len(fosiles_nuevas)} entrada(s) de NUEVAS ya no existen en la app: bórralas.",
            file=sys.stderr,
        )
        for op in fosiles_nuevas:
            print(f"  - {op}", file=sys.stderr)
    if duplicadas:
        print(
            f"\n{len(duplicadas)} entrada(s) de NUEVAS ya están en la línea base: "
            "una operación heredada no necesita motivo, quitalas de NUEVAS.",
            file=sys.stderr,
        )
        for op in duplicadas:
            print(f"  - {op}", file=sys.stderr)
    if motivos_cortos:
        print(
            f"\n{len(motivos_cortos)} motivo(s) de NUEVAS no dicen qué superficie "
            f"existente se miró (menos de {MOTIVO_MINIMO} caracteres):",
            file=sys.stderr,
        )
        for op in motivos_cortos:
            print(f"  - {op}", file=sys.stderr)

    if sin_justificar or fosiles_base or fosiles_nuevas or duplicadas or motivos_cortos:
        return 1

    heredadas = len(actuales & base)
    print(
        f"Ratchet de superficie OK: {len(actuales)} operaciones "
        f"({heredadas} de la línea base, {len(NUEVAS)} añadidas con motivo)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
