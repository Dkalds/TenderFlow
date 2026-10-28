"""Crea la alerta por defecto de las organizaciones que ya existían (D53, B1).

Desde el plan 2026-10, guardar el ámbito de una organización sin ninguna regla
de vigilancia le crea una alerta diaria
(``services.watchlist_rules.asegurar_alerta_por_defecto``). Las organizaciones
que configuraron sus tecnologías antes no pasan por ese guardado: este script
hace por ellas lo mismo, con la misma función, a nombre de su owner.

Por defecto **solo cuenta**; escribe con ``--aplicar``::

    python scripts/crear_alertas_por_defecto.py            # cuenta, no escribe
    python scripts/crear_alertas_por_defecto.py --aplicar  # crea las reglas
    python scripts/crear_alertas_por_defecto.py --json

Requiere ``DATABASE_URL``. Contra producción lo ejecuta el propietario
(AGENTS.md §6). Es idempotente: una organización que ya tiene alguna regla, o
que ya recibió su alerta por defecto alguna vez y la borró, no se toca.
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

from db.repositories.organizations import OrganizationRepository  # noqa: E402
from db.repositories.watchlist_rules import MARCA_ALERTA_POR_DEFECTO  # noqa: E402
from services.organizations import ajustes_guardados  # noqa: E402
from services.watchlist_rules import (  # noqa: E402
    asegurar_alerta_por_defecto,
    reglas_por_defecto,
)


def _ajustes_crudos(valor: str | None) -> dict[str, Any]:
    """``settings_json`` como dict; uno ilegible cuenta como vacío."""
    try:
        leido = json.loads(valor or "{}")
    except (TypeError, ValueError):
        return {}
    return leido if isinstance(leido, dict) else {}


def recorrer(*, aplicar: bool) -> dict[str, Any]:
    """Clasifica cada organización y, con ``aplicar``, crea lo que falta.

    Las categorías son excluyentes y en este orden: sin ámbito del que sacar
    una regla, alerta ya creada alguna vez, alguna regla ya existente, sin
    owner activo, y pendiente. Una pendiente puede acabar sin reglas al
    aplicar —su owner no tiene correo, o alguien creó una regla entre la
    lectura y la escritura—, y por eso se cuentan aparte las creadas.
    """
    resumen: dict[str, Any] = {
        "aplicado": aplicar,
        "organizaciones": 0,
        "sin_ambito": 0,
        "ya_tuvo_alerta": 0,
        "con_reglas": 0,
        "sin_owner": 0,
        "pendientes": [],
        "reglas_creadas": 0,
        "organizaciones_con_alerta_nueva": 0,
    }
    for fila in OrganizationRepository().para_alerta_por_defecto():
        resumen["organizaciones"] += 1
        organization_id = fila["id"]
        crudos = _ajustes_crudos(fila["settings_json"])
        ajustes = ajustes_guardados(crudos, organization_id)
        reglas = reglas_por_defecto(ajustes)
        if not reglas:
            resumen["sin_ambito"] += 1
            continue
        if MARCA_ALERTA_POR_DEFECTO in crudos:
            resumen["ya_tuvo_alerta"] += 1
            continue
        if fila["tiene_reglas"]:
            resumen["con_reglas"] += 1
            continue
        owner = fila["owner_user_id"]
        if owner is None:
            resumen["sin_owner"] += 1
            continue
        resumen["pendientes"].append(
            {"organization_id": organization_id, "reglas": [r.nombre for r in reglas]}
        )
        if aplicar:
            ids = asegurar_alerta_por_defecto(organization_id, owner, ajustes)
            resumen["reglas_creadas"] += len(ids)
            resumen["organizaciones_con_alerta_nueva"] += int(bool(ids))
    return resumen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="Crea las reglas de verdad. Sin esta opción solo se cuenta.",
    )
    parser.add_argument("--json", action="store_true", help="Salida en JSON")
    args = parser.parse_args(argv)

    resumen = recorrer(aplicar=args.aplicar)
    if args.json:
        print(json.dumps(resumen, indent=2, ensure_ascii=False))
        return 0

    pendientes = resumen["pendientes"]
    print(f"Organizaciones: {resumen['organizaciones']}")
    print(f"  sin tecnologías ni CPVs:          {resumen['sin_ambito']}")
    print(f"  ya recibieron su alerta:          {resumen['ya_tuvo_alerta']}")
    print(f"  ya tienen alguna regla:           {resumen['con_reglas']}")
    print(f"  sin owner activo:                 {resumen['sin_owner']}")
    print(f"  pendientes:                       {len(pendientes)}")
    for p in pendientes:
        print(f"    org {p['organization_id']}: {', '.join(str(n) for n in p['reglas'])}")
    if args.aplicar:
        print(
            f"Creadas {resumen['reglas_creadas']} reglas en "
            f"{resumen['organizaciones_con_alerta_nueva']} organizaciones."
        )
    elif pendientes:
        print("Sin escribir nada. Repetí con --aplicar para crearlas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
