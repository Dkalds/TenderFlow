"""Piezas compartidas por las familias de ``/licitaciones``.

Aquí sólo hay lo que **usan varias**: los repositorios (uno por proceso, no uno
por petición), las dos validaciones de parámetros, el cursor opaco, el ETag y
el clasificador perezoso. Nada que use una sola familia baja hasta aquí: un
módulo «común» al que todo el mundo añade es el mismo fichero de 1.600 líneas
con otro nombre.
"""

from __future__ import annotations

import base64
import json
import re
from datetime import date
from typing import Any

from fastapi import HTTPException, status

from api.errors import sunset_anunciado
from db.repositories.adjudicaciones import AdjudicacionRepository
from db.repositories.documentos import DocumentosRepository
from db.repositories.licitaciones import LicitacionRepository
from observability.logging import get_logger

log = get_logger(__name__)

#: Apagado del listado por offset. Anunciado el 2026-09-06 con la ventana
#: de 90 días de `DEPRECATION_WINDOW_DAYS`; la sucesora es
#: `/licitaciones/cursor`, que ya sirve el mismo dato sin `COUNT(*)`.
SUNSET_LISTADO_POR_OFFSET = sunset_anunciado(date(2027, 1, 15), anunciado=date(2026, 9, 6))

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_QUERY_LENGTH = 200

# Singletons — instanciados una vez
_lic_repo = LicitacionRepository()
_adj_repo = AdjudicacionRepository()
_doc_repo = DocumentosRepository()


def _validate_date(value: str | None, field: str) -> None:
    """Raise 422 si el valor no es YYYY-MM-DD."""
    if value is not None and not _DATE_RE.match(value):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Parámetro '{field}' debe tener formato YYYY-MM-DD, recibido: {value!r}",
        )


def _validate_query(value: str | None) -> None:
    """Raise 422 si la query de búsqueda excede el límite de caracteres."""
    if value is not None and len(value) > _MAX_QUERY_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Parámetro 'q' excede el máximo de {_MAX_QUERY_LENGTH} caracteres.",
        )


# ── Cursor helpers ────────────────────────────────────────────────────────


def _encode_cursor(fecha: str | None, id_externo: str) -> str:
    raw = f"{fecha or ''}|{id_externo}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    if len(cursor) > 512:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cursor demasiado largo.",
        )
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor + padding).decode()
        fecha, id_externo = raw.split("|", 1)
        return fecha, id_externo
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cursor inválido.",
        ) from exc


#: Prefijo del cursor de un orden distinto del de fecha. El de fecha conserva
#: su forma de siempre (``fecha|id``) para que los cursores ya emitidos sigan
#: valiendo; los nuevos llevan el orden dentro, así que un cursor de «por
#: importe» no se puede reutilizar con «por título» sin que se note.
_PREFIJO_CURSOR_ORDEN = "o1|"


def _encode_cursor_orden(sort: str, valor: str | float | None, id_externo: str) -> str:
    """Cursor opaco de un listado ordenado por ``sort`` (keyset ``(valor, id)``)."""
    raw = _PREFIJO_CURSOR_ORDEN + json.dumps([sort, valor, id_externo], ensure_ascii=False)
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor_orden(cursor: str, sort: str) -> tuple[str | float | None, str]:
    """``(valor, id_externo)`` de un cursor de :func:`_encode_cursor_orden`.

    400 si el cursor no es de este formato o es de **otro orden**: seguir
    paginando «por título» con la posición de «por importe» devolvería una
    página que no sigue a ninguna.
    """
    if len(cursor) > 512:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cursor demasiado largo.",
        )
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor + padding).decode()
        if not raw.startswith(_PREFIJO_CURSOR_ORDEN):
            raise ValueError("cursor sin orden")
        orden, valor, id_externo = json.loads(raw[len(_PREFIJO_CURSOR_ORDEN) :])
        if orden != sort or not isinstance(id_externo, str):
            raise ValueError("cursor de otro orden")
        if valor is not None and not isinstance(valor, str | int | float):
            raise ValueError("valor de cursor inválido")
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cursor inválido para este orden.",
        ) from exc
    return valor, id_externo


# ── SAPClassifier singleton ───────────────────────────────────────────────


def _get_classifier() -> Any:
    """Devuelve el SAPClassifier activo (caché de proceso con lock y TTL).

    La caché vive en ``api.model_cache`` para que ``/models/{name}/activate``
    pueda invalidarla sin importar esta ruta.
    """
    from api.model_cache import get_classifier

    return get_classifier()
