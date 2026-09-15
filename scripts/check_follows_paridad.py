#!/usr/bin/env python3
"""Mide la paridad entre ``follows`` y las tres tablas que lo alimentan (ADR-031 §B).

Por qué existe
--------------
ADR-031 pone una condición explícita antes de mover una sola lectura a
``follows``: reproducir, **para cada usuario**, favoritos + empresas +
descartes desde la tabla unificada con **cero diferencias**, medido contra
producción. Sin ese número, retirar los endpoints antiguos no es una migración
sino una apuesta con el dato del cliente.

Este script es ese número. No repara nada y no escribe: sólo cuenta y dice qué
falta y qué sobra.

Qué compara
-----------
Tres pares, cada uno con la proyección que el backfill de v130 declaró:

* ``watchlist_items``    → ``(user_key, 'licitacion', id_externo, 'seguir')``
* ``watchlist_empresas`` → ``(user_key, 'empresa', empresa_id::text, 'seguir')``
* ``radar_dismissals``   → ``(user_key, 'licitacion', id_externo, 'descartar')``

Y devuelve, por par:

- ``faltan``  — está en la tabla de origen y no en ``follows``. **Es el que
  bloquea la migración:** cada fila aquí es un favorito que el usuario perdería
  el día que la lectura cambie de sitio.
- ``sobran``  — está en ``follows`` y no en el origen. Menos grave, pero no
  inocuo: normalmente es un borrado que no se propagó, y el usuario vería
  reaparecer algo que quitó.
- ``usuarios_con_diferencias`` — porque «12 filas» no dice si es un usuario
  raro o el sistema entero.

Uso::

    python scripts/check_follows_paridad.py            # texto, exit 1 si faltan
    python scripts/check_follows_paridad.py --json     # para un job
    python scripts/check_follows_paridad.py --detalle 20

Exit 0 sólo con ``faltan == 0`` en los tres pares. ``sobran`` avisa pero no
tumba: no impide que la lectura se mueva, y su causa suele ser el histórico de
un borrado anterior a la escritura doble.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Diferencia:
    """Resultado de comparar una tabla de origen con ``follows``."""

    tabla: str
    target_type: str
    kind: str
    filas_origen: int = 0
    filas_follows: int = 0
    faltan: int = 0
    sobran: int = 0
    usuarios_con_diferencias: int = 0
    ejemplos_faltan: list[str] = field(default_factory=list)
    ejemplos_sobran: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Sólo ``faltan`` bloquea. Ver la cabecera."""
        return self.faltan == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "tabla": self.tabla,
            "target_type": self.target_type,
            "kind": self.kind,
            "filas_origen": self.filas_origen,
            "filas_follows": self.filas_follows,
            "faltan": self.faltan,
            "sobran": self.sobran,
            "usuarios_con_diferencias": self.usuarios_con_diferencias,
            "ejemplos_faltan": self.ejemplos_faltan,
            "ejemplos_sobran": self.ejemplos_sobran,
            "ok": self.ok,
        }


def medir(detalle: int = 5) -> list[Diferencia]:
    """Los tres pares, en el orden de ``PARES_DE_ORIGEN``.

    El SQL está en ``db/repositories/follows.py``: en ``scripts/`` está
    prohibido (ADR-022, y el ratchet TID251 lo verifica). Aquí sólo se le da
    forma al resultado.
    """
    from db.repositories.follows import PARES_DE_ORIGEN, paridad_con_origen

    salida: list[Diferencia] = []
    for tabla, expr, target_type, kind in PARES_DE_ORIGEN:
        crudo = paridad_con_origen(tabla, expr, target_type, kind, ejemplos=detalle)
        faltan = crudo["faltan"]
        sobran = crudo["sobran"]
        salida.append(
            Diferencia(
                tabla=tabla,
                target_type=target_type,
                kind=kind,
                filas_origen=int(crudo["filas_origen"]),
                filas_follows=int(crudo["filas_follows"]),
                faltan=len(faltan),
                sobran=len(sobran),
                usuarios_con_diferencias=len({u for u, _ in faltan} | {u for u, _ in sobran}),
                ejemplos_faltan=[f"{u}\u2192{t}" for u, t in faltan[:detalle]],
                ejemplos_sobran=[f"{u}\u2192{t}" for u, t in sobran[:detalle]],
            )
        )
    return salida


def _render(diferencias: list[Diferencia]) -> str:
    lineas = ["Paridad follows ↔ tablas de origen (ADR-031 §B)", ""]
    lineas.append(f"{'origen':<22}{'origen':>9}{'follows':>9}{'faltan':>8}{'sobran':>8}  estado")
    for d in diferencias:
        estado = "OK" if d.ok else "BLOQUEA"
        lineas.append(
            f"{d.tabla:<22}{d.filas_origen:>9}{d.filas_follows:>9}"
            f"{d.faltan:>8}{d.sobran:>8}  {estado}"
        )
    lineas.append("")

    for d in diferencias:
        if d.ejemplos_faltan:
            lineas.append(f"  {d.tabla}: sin reflejar en follows → {', '.join(d.ejemplos_faltan)}")
        if d.ejemplos_sobran:
            lineas.append(f"  {d.tabla}: en follows sin origen  → {', '.join(d.ejemplos_sobran)}")

    if all(d.ok for d in diferencias):
        lineas.append(
            "\nCero filas sin reflejar: la condición de ADR-031 §B se cumple en esta base. "
            "Mover la lectura a `follows` deja de ser una apuesta."
        )
    else:
        lineas.append(
            "\nHay filas de origen sin reflejar en `follows`. NO mover ninguna lectura: "
            "cada una es un seguimiento que el usuario perdería. "
            "Reejecutá el backfill de v130 (es idempotente) y volvé a medir."
        )
    if any(d.sobran for d in diferencias):
        lineas.append(
            "Las filas que sobran no bloquean, pero revisalas: suelen ser borrados "
            "anteriores a la escritura doble que nadie propagó."
        )
    return "\n".join(lineas)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="salida legible por máquina")
    parser.add_argument(
        "--detalle", type=int, default=5, help="cuántos ejemplos mostrar por lado (def. 5)"
    )
    args = parser.parse_args()

    diferencias = medir(detalle=max(0, args.detalle))
    if args.json:
        print(
            json.dumps(
                {
                    "ok": all(d.ok for d in diferencias),
                    "pares": [d.as_dict() for d in diferencias],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(_render(diferencias))
    return 0 if all(d.ok for d in diferencias) else 1


if __name__ == "__main__":
    raise SystemExit(main())
