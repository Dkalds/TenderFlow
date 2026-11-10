"""Auditoría diaria de la verdad del dato, como job del plano de cron.

Hasta el 2026-11-10 la lanzaba ``.github/workflows/domain-truth.yml`` con
``scripts/audit_domain_truth.py --check --alert``. Aquí mide y evalúa en el
mismo proceso, con el pool que el plano ya tiene abierto: un intérprete aparte
abriría un tercer juego de conexiones contra el mismo pooler.

Dos diferencias con el script, a sabiendas:

* No mide la sección (b), los multilote de los ZIP mensuales: necesita los ZIP
  cacheados en disco, que el contenedor no tiene, y ningún umbral la evalúa.
* El workflow subía las mediciones como artefacto, y de ahí salió la
  recalibración de umbrales del 2026-09-18. Aquí van en una línea de log
  (``domain_truth_mediciones``), que es de donde habrá que sacarlas.
"""

from __future__ import annotations

import json
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)


def run() -> dict[str, Any]:
    """Mide, compara con los umbrales y avisa por correo de lo que se supere."""
    from observability import AlertLevel, notify
    from services.verdad_dominio import evaluar, medir_bd

    datos = medir_bd()
    violaciones = evaluar(datos)
    log.info(
        "domain_truth_mediciones",
        mediciones=json.dumps(datos, default=str),
        violaciones=violaciones,
    )
    if violaciones:
        notify(
            AlertLevel.WARN,
            "Auditoría de verdad del dato: umbrales superados",
            body="\n".join(f"- {v}" for v in violaciones),
            violaciones=len(violaciones),
        )
    return {"violaciones": len(violaciones)}
