#!/usr/bin/env python
"""Asigna las filas sin organización a la organización personal de su usuario.

**Es un UPDATE de datos, no una migración de schema**: no hay revisión Alembic
y no debe haberla. El schema ya tiene la columna; lo que falta es rellenarla en
las filas que se escribieron cuando ``organization_id`` era opcional.

Por qué hace falta: los repositorios de datos de usuario (``watchlist_items``,
``saved_filters``, ``watchlist_empresas``, ``user_profiles``,
``user_notifications``…) dejaron de aceptar ``organization_id=None`` — antes,
omitirla escribía una fila con organización nula que la consulta *con* ámbito
no volvía a ver nunca. Esas filas siguen en la base: para su dueño, sus
favoritos y sus filtros guardados simplemente no están.

Cada fila huérfana se adjudica a la organización **personal** de su usuario,
nunca a una compartida: el dato lo creó una persona antes de que existieran los
equipos, así que su ámbito honesto es el suyo propio. Quien quiera compartirlo
después lo hace explícitamente desde el producto.

Uso::

    python scripts/asignar_organizacion_huerfanos.py              # dry-run (default)
    python scripts/asignar_organizacion_huerfanos.py --aplicar    # escribe
    python scripts/asignar_organizacion_huerfanos.py --aplicar --limite-usuarios 5000

Requiere ``DATABASE_URL`` (o ``TEST_DATABASE_URL`` en entornos de prueba); usa
el mismo pool que la aplicación. Es idempotente: una segunda pasada no cambia
nada porque ya no queda ninguna fila con ``organization_id IS NULL``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.repositories.organizations import OrganizationRepository
from db.tenancy_backfill import contar_huerfanos
from db.users import list_users
from shared.identity import user_key_from_email


def _informe(titulo: str, conteos: dict[str, int]) -> int:
    total = sum(conteos.values())
    print(f"\n{titulo}")
    ancho = max((len(t) for t in conteos), default=0)
    for tabla, n in sorted(conteos.items(), key=lambda kv: (-kv[1], kv[0])):
        marca = "  " if n == 0 else "→ "
        print(f"  {marca}{tabla.ljust(ancho)}  {n:>8}")
    print(f"  {'TOTAL'.ljust(ancho + 2)}  {total:>8}")
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Solo cuenta; no escribe. Es el comportamiento por defecto.",
    )
    grupo.add_argument(
        "--aplicar",
        action="store_true",
        help="Ejecuta los UPDATE. Sin esta bandera no se escribe nada.",
    )
    parser.add_argument(
        "--limite-usuarios",
        type=int,
        default=10000,
        help="Tope de usuarios a recorrer al aplicar (default: 10000).",
    )
    args = parser.parse_args(argv)
    aplicar = bool(args.aplicar)

    antes = contar_huerfanos()
    total_antes = _informe("Filas con organization_id IS NULL (antes):", antes)

    if total_antes == 0:
        print("\nNada que hacer: no hay filas huérfanas.")
        return 0

    if not aplicar:
        print(
            "\nDRY-RUN: no se ha escrito nada. Repetí con --aplicar para "
            "adjudicar estas filas a la organización personal de su usuario."
        )
        return 0

    repo = OrganizationRepository()
    usuarios = list_users(limit=args.limite_usuarios, include_deactivated=True)
    print(f"\nAplicando sobre {len(usuarios)} usuario(s)…")

    tocadas = 0
    fallos = 0
    for user in usuarios:
        user_id = int(user["id"])
        user_key = user_key_from_email(user.get("email"), user_id)
        try:
            # Reutiliza el camino que ya usa el producto (routes → claim_legacy_scope):
            # crea la organización personal si falta y adjudica solo filas sin ámbito.
            tocadas += repo.claim_legacy_rows(user_id, user_key)
        except Exception as exc:  # pragma: no cover - depende del estado de la BD
            fallos += 1
            print(f"  ! usuario {user_id}: {type(exc).__name__}: {exc}")

    print(f"\nFilas adjudicadas: {tocadas}. Usuarios con error: {fallos}.")

    despues = contar_huerfanos()
    restantes = _informe("Filas con organization_id IS NULL (después):", despues)
    if restantes:
        print(
            "\nQuedan filas huérfanas: pertenecen a `user_key` que no corresponde "
            "a ningún usuario de la tabla `users` (cuentas borradas, o datos "
            "sembrados a mano). Revisalas antes de decidir qué hacer con ellas: "
            "adjudicarlas a alguien sería inventarse un dueño."
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
