"""Verificador de la reingesta única de PLACSP (solo lectura).

Mide en la base lo que la reingesta de los ZIP mensuales debe corregir
(``docs/runbooks/reingesta-unica-placsp.md``) y lo compara con las puertas del
ítem V2 del plan 2026-10:

- **Base del importe** (ADR-032): ``importe_tipo`` desconocido o nulo en filas
  PLACSP. Puerta: por debajo del 10 %.
- **Umbral de la solvencia económica** (P2 «condiciones oficiales de CODICE»):
  requisitos económicos con ``umbral_importe`` no nulo. Informativa: la fuente
  no lo publica en todos, y el porcentaje esperado sale de
  ``scripts/medir_terminos_codice.py``, no de aquí.
- **Arreglos del parser del 2026-10-25**: ``provincia = 'España'``, importes a
  0 en ``adjudicaciones`` y garantías, y ``fecha_publicacion`` con hora.
  Puerta: 0 en las filas del feed (las de ``placsp_watched_company_awards`` se
  enseñan aparte: esta reingesta no las alcanza).
- **Colisiones de expediente** (RFC de identidad): pisadas en
  ``licitaciones_history``, filas sin ``organo_ref_fuente`` y expedientes que
  ya conviven con la clave nueva. Informativas aquí: sus puertas son las del
  RFC y las mide también ``scripts/inventario_pisadas_placsp.py``.

Uso::

    python scripts/verificar_reingesta.py                       # todo PLACSP
    python scripts/verificar_reingesta.py --desde 2026-11-02    # solo lo que tocó la reingesta
    python scripts/verificar_reingesta.py --json                # para anotar
    python scripts/verificar_reingesta.py --estricto            # exit 1 si falla una puerta

``--desde`` filtra por ``fecha_extraccion``: lo que la reingesta no reescribió
(filas que el filtro TI ya no admite, meses fuera del rango) queda fuera, que
es lo que separa «no se corrigió» de «no se reingirió». ``--sin-historial``
omite la consulta de pisadas, la única que recorre ``licitaciones_history``.

Solo lee (``connect_read``). Necesita ``DATABASE_URL``. El SQL vive en
``db/repositories/verificacion_reingesta.py`` y ``db/repositories/identidad.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from typing import Any

#: Puerta del plan 2026-10 (V2) para la base del importe en filas PLACSP.
UMBRAL_IMPORTE_DESCONOCIDO = 0.10


@dataclass(frozen=True)
class Puerta:
    """Una comprobación con su valor medido y si pasa."""

    nombre: str
    valor: str
    objetivo: str
    pasa: bool | None  # None = informativa, no decide


def _pct(parte: int, total: int) -> float:
    return parte / total if total else 0.0


def evaluar_puertas(cifras: dict[str, Any]) -> list[Puerta]:
    """Las puertas de V2 a partir de las cifras de :func:`medir`. Sin E/S."""
    lic = cifras["licitaciones"]
    sol = cifras["solvencia_economica"]
    feed = next((g for g in cifras["ceros"] if g["grupo"] == "placsp"), None)
    desconocido = _pct(lic["importe_tipo_desconocido"], lic["filas"])
    puertas = [
        Puerta(
            "importe_tipo desconocido o nulo (PLACSP)",
            f"{lic['importe_tipo_desconocido']} de {lic['filas']} ({desconocido:.1%})",
            f"< {UMBRAL_IMPORTE_DESCONOCIDO:.0%}",
            lic["filas"] > 0 and desconocido < UMBRAL_IMPORTE_DESCONOCIDO,
        ),
        Puerta(
            "solvencia económica con umbral",
            f"{sol['con_umbral']} de {sol['requisitos']} requisitos; "
            f"{sol['licitaciones_con_umbral']} de {sol['licitaciones']} licitaciones",
            "no nulo donde la fuente lo publica (comparar con medir_terminos_codice)",
            None,
        ),
        Puerta(
            "provincia = 'España'", str(lic["provincia_espana"]), "0", lic["provincia_espana"] == 0
        ),
        Puerta(
            "fecha_publicacion con hora",
            str(lic["fecha_publicacion_con_hora"]),
            "0",
            lic["fecha_publicacion_con_hora"] == 0,
        ),
    ]
    adj0 = feed["adjudicaciones_con_cero"] if feed else 0
    gar0 = feed["garantias_con_cero"] if feed else 0
    puertas.append(
        Puerta(
            "adjudicaciones con importe 0 (feed PLACSP)",
            f"{adj0} de {feed['adjudicaciones'] if feed else 0}",
            "0",
            adj0 == 0,
        )
    )
    puertas.append(
        Puerta(
            "garantías con porcentaje o importe 0 (feed PLACSP)",
            f"{gar0} de {feed['garantias'] if feed else 0}",
            "0",
            gar0 == 0,
        )
    )
    for grupo in cifras["ceros"]:
        if grupo["grupo"] == "placsp":
            continue
        puertas.append(
            Puerta(
                f"ceros en {grupo['grupo']} (no los reingiere el feed)",
                f"{grupo['adjudicaciones_con_cero']} adjudicaciones, "
                f"{grupo['garantias_con_cero']} garantías",
                "informativa",
                None,
            )
        )
    col = cifras.get("colisiones")
    if col is not None:
        puertas.append(
            Puerta(
                "pisadas en licitaciones_history (cota inferior)",
                f"{col['pares_seguros']} pares seguros, {col['pares_dudosos']} dudosos, "
                f"{col['ids_afectados']} ids",
                "las recupera la fase 4 del RFC; comparar antes/después",
                None,
            )
        )
    puertas.append(
        Puerta(
            "filas PLACSP sin organo_ref_fuente",
            str(sum(cifras["sin_organo_ref"].values())),
            "0 antes de la re-key (puerta 1 del RFC)",
            None,
        )
    )
    puertas.append(
        Puerta(
            "expedientes que conviven con la clave nueva",
            str(cifras["conviven"]),
            "> 0 tras la fase B (consulta 9 del RFC)",
            None,
        )
    )
    return puertas


def medir(*, desde: str | None, con_historial: bool) -> dict[str, Any]:
    """Todas las cifras, en un dict serializable."""
    from db.repositories.identidad import (
        contar_expedientes_que_conviven,
        contar_placsp_sin_organo_ref,
        inventario_pisadas_placsp,
        resumen_pisadas_placsp,
    )
    from db.repositories.verificacion_reingesta import (
        ceros_en_hijas,
        licitaciones_placsp,
        solvencia_economica,
    )

    cifras: dict[str, Any] = {
        "desde": desde,
        "licitaciones": dict(licitaciones_placsp(desde=desde)),
        "solvencia_economica": dict(solvencia_economica(desde=desde)),
        "ceros": [dict(g) for g in ceros_en_hijas(desde=desde)],
        "sin_organo_ref": contar_placsp_sin_organo_ref(),
        "conviven": contar_expedientes_que_conviven(),
        "colisiones": None,
    }
    if con_historial:
        cifras["colisiones"] = resumen_pisadas_placsp(inventario_pisadas_placsp())._asdict()
    return cifras


def _imprimir(puertas: list[Puerta], desde: str | None) -> None:
    alcance = f"filas con fecha_extraccion >= {desde}" if desde else "todas las filas PLACSP"
    print(f"VERIFICACIÓN DE LA REINGESTA ÚNICA DE PLACSP ({alcance})")
    for p in puertas:
        marca = "  ··" if p.pasa is None else ("  OK" if p.pasa else "  NO")
        print(f"{marca}  {p.nombre}: {p.valor}  [objetivo: {p.objetivo}]")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verificador de la reingesta de PLACSP")
    parser.add_argument(
        "--desde", default=None, help="ISO; solo filas con fecha_extraccion >= desde"
    )
    parser.add_argument("--json", action="store_true", help="Cifras y puertas en JSON")
    parser.add_argument(
        "--sin-historial", action="store_true", help="No recorre licitaciones_history"
    )
    parser.add_argument(
        "--estricto", action="store_true", help="Exit 1 si alguna puerta decisoria falla"
    )
    args = parser.parse_args(argv)

    cifras = medir(desde=args.desde, con_historial=not args.sin_historial)
    puertas = evaluar_puertas(cifras)
    if args.json:
        salida = {"cifras": cifras, "puertas": [asdict(p) for p in puertas]}
        print(json.dumps(salida, ensure_ascii=False, indent=2, default=str))
    else:
        _imprimir(puertas, args.desde)
    if args.estricto and any(p.pasa is False for p in puertas):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
