"""Acceso de lectura a ``contrato_eventos`` (eventos del ciclo de vida del contrato).

La tabla la escribe ``services/contract_events.py``, que la deriva de
``licitaciones_history`` (Fase 4). Este módulo existe para las consultas de
lectura que otros módulos necesitan sin abrir conexión por su cuenta —
ADR-022: todo el SQL vive en ``db/``.

Módulo de funciones, no clase: es el mismo estrato que ``db/repositories/*``
(AGENTS.md §3.10), y las consultas de esta tabla no comparten estado ni
filtros que justifiquen agruparlas en un repository.
"""

from __future__ import annotations

from collections import defaultdict

from db.database import connect_read
from db.repositories.base import rows_to_dicts

# Los dos únicos tipos que hoy se usan como proxy de satisfacción del cliente
# en el etiquetado de retención. Se acotan en SQL para no traer a Python el
# resto del log de eventos (adjudicacion, formalizacion, anulacion, ...).
TIPOS_SATISFACCION: tuple[str, ...] = ("modificacion", "prorroga")


def contar_por_licitacion_y_tipo(
    tipos: tuple[str, ...] = TIPOS_SATISFACCION,
) -> dict[str, dict[str, int]]:
    """Nº de eventos por licitación y tipo: ``{licitacion_id: {tipo: n}}``.

    Las licitaciones sin eventos de los tipos pedidos **no aparecen** en el
    resultado; el llamador decide qué significa la ausencia (en el etiquetado
    de retención, cero).

    El SQL vivía en ``services/ml/retencion_labels.py``; se movió aquí al sacar
    ese módulo del ratchet TID251.
    """
    # Lo interpolado es solo la lista de `%s` (una por tipo pedido); los valores
    # viajan como parámetros, nunca dentro del SQL.
    placeholders = ",".join("%s" for _ in tipos)
    sql = (
        "SELECT licitacion_id, tipo, COUNT(*) AS n FROM contrato_eventos "
        f"WHERE tipo IN ({placeholders}) GROUP BY licitacion_id, tipo"
    )
    with connect_read() as c:
        rows = rows_to_dicts(c.execute(sql, tipos))
    out: dict[str, dict[str, int]] = defaultdict(dict)
    for r in rows:
        out[str(r["licitacion_id"])][str(r["tipo"])] = int(r["n"])
    return out
