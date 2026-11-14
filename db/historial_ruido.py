"""Filas de ``licitaciones_history`` que solo registran el ruido de float4 en ``importe``.

Mientras ``licitaciones.importe`` fue ``real`` en producción (hasta ``v156``,
aplicada el 2026-11-06), el detector de diffs de ``db/upsert.py`` comparaba con
igualdad exacta un valor redondeado a float4 contra el float8 del conector y
escribía una fila de historial con ``changed_fields='importe'`` en cada
reingesta de un expediente intacto. ``services/contract_events.py`` derivó de
algunas de ellas un evento ``modificacion`` de ``importe``. Este módulo da el
SQL para encontrarlas y borrarlas; qué fila es ruido lo decide quien llama
(``scripts/limpiar_ruido_importe_historial.py``).

Cada snapshot es el estado *anterior* al cambio de su fila, así que el importe
«después» de una fila es el del snapshot siguiente del mismo expediente o, si
es la última, el de la fila actual de ``licitaciones``. Los snapshots de más de
50 000 caracteres están truncados y no son JSON válido: el importe se extrae
con una expresión regular en SQL, que además evita traer el snapshot entero.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypedDict

from db.database import connect, connect_read
from db.repositories.base import rows_to_dicts

# `json.dumps` escribe la clave como `"importe": <valor>`. El lookbehind
# descarta la misma secuencia escapada dentro de un texto (`\"importe\": `).
_IMPORTE_EN_SNAPSHOT = r'(?<!\\)"importe": ([^,}]+)'

_CANDIDATOS_SQL = """
SELECT h.id AS history_id,
       h.id_externo,
       substring(h.snapshot_json FROM %(patron)s::text) AS antes,
       sig.id AS siguiente_id,
       substring(sig.snapshot_json FROM %(patron)s::text) AS despues_siguiente,
       l.importe AS importe_actual
FROM licitaciones_history h
LEFT JOIN LATERAL (
    SELECT n.id, n.snapshot_json
    FROM licitaciones_history n
    WHERE n.id_externo = h.id_externo AND n.id > h.id
    ORDER BY n.id
    LIMIT 1
) sig ON true
LEFT JOIN licitaciones l ON l.id_externo = h.id_externo
WHERE h.id > %(desde_id)s AND h.changed_fields = 'importe'
ORDER BY h.id
LIMIT %(lote)s
"""


class CandidatoRuido(TypedDict):
    """Una fila de historial con solo ``importe`` cambiado, con su antes y después."""

    history_id: int
    id_externo: str
    antes: float | None
    despues: float | None


def _numero(valor: object) -> float | None:
    """El importe de un snapshot o de la fila actual; ``None`` si no se puede leer.

    Un snapshot truncado a mitad del número deja un token como
    ``1234...(truncado)``: no es un número y la fila no se juzga.
    """
    if valor is None:
        return None
    if isinstance(valor, int | float):
        return float(valor)
    texto = str(valor).strip().strip('"')
    if texto == "null":
        return None
    try:
        return float(texto)
    except ValueError:
        return None


def candidatos_ruido_importe(desde_id: int, lote: int) -> list[CandidatoRuido]:
    """Hasta ``lote`` filas con ``changed_fields='importe'`` e ``id > desde_id``, por id.

    ``despues`` sale del snapshot siguiente del mismo expediente o, si no lo
    hay, de ``licitaciones.importe``; ``None`` si no se pudo leer (snapshot
    truncado antes del importe, licitación borrada).
    """
    with connect_read() as c:
        filas = rows_to_dicts(
            c.execute(
                _CANDIDATOS_SQL,
                {"patron": _IMPORTE_EN_SNAPSHOT, "desde_id": desde_id, "lote": lote},
            )
        )
    return [
        CandidatoRuido(
            history_id=int(f["history_id"]),
            id_externo=str(f["id_externo"]),
            antes=_numero(f["antes"]),
            despues=_numero(
                f["despues_siguiente"] if f["siguiente_id"] is not None else f["importe_actual"]
            ),
        )
        for f in filas
    ]


def filas_a_borrar(ids: Sequence[int]) -> dict[str, list[dict[str, Any]]]:
    """Las filas enteras que ``borrar_ruido_importe(ids)`` borraría, por tabla.

    Es el respaldo con el que se deshace el borrado: con todas las columnas, un
    ``INSERT`` las restaura tal cual. Mismos predicados que el DELETE.
    """
    if not ids:
        return {"licitaciones_history": [], "contrato_eventos": []}
    lista = list(ids)
    with connect_read() as c:
        historial = rows_to_dicts(
            c.execute(
                "SELECT * FROM licitaciones_history "  # SELECT *: respaldo de la fila entera
                "WHERE id = ANY(%s) AND changed_fields = 'importe' ORDER BY id",
                (lista,),
            )
        )
        eventos = rows_to_dicts(
            c.execute(
                "SELECT * FROM contrato_eventos "  # SELECT *: respaldo de la fila entera
                "WHERE history_id = ANY(%s) AND tipo = 'modificacion' AND campo = 'importe' "
                "ORDER BY id",
                (lista,),
            )
        )
    return {"licitaciones_history": historial, "contrato_eventos": eventos}


def borrar_ruido_importe(ids: Sequence[int]) -> tuple[int, int]:
    """Borra estas filas de historial y los eventos de importe derivados de ellas.

    Devuelve ``(eventos, filas_de_historial)`` borrados. Una transacción: si
    algo falla, nada. ``contrato_eventos.history_id`` no tiene FK, así que los
    eventos se borran primero a mano; solo los de ``modificacion`` de
    ``importe``, que es lo único que ``services/contract_events.py`` deriva de
    una fila con ``changed_fields='importe'``. El ``changed_fields`` del DELETE
    impide borrar por error una fila con otro cambio.
    """
    if not ids:
        return 0, 0
    lista = list(ids)
    with connect() as c:
        eventos = c.execute(
            "DELETE FROM contrato_eventos "
            "WHERE history_id = ANY(%s) AND tipo = 'modificacion' AND campo = 'importe'",
            (lista,),
        ).rowcount
        historial = c.execute(
            "DELETE FROM licitaciones_history WHERE id = ANY(%s) AND changed_fields = 'importe'",
            (lista,),
        ).rowcount
    return eventos or 0, historial or 0
