"""Envelopes genéricos de mutaciones y conteos (``StatusOk``, ``CreatedId``…)."""

from __future__ import annotations

from pydantic import BaseModel

# ── Envelopes genéricos del contrato (tipado de operaciones opacas) ─────────
#
# Nota de modelado (backlog «Tipar el contrato API↔web»): los campos van SIN
# default cuando la query siempre devuelve la clave (valor posiblemente None).
# Un default los marcaría opcionales en OpenAPI y obligaría al cliente a
# tratar `undefined` donde nunca ocurre.


class StatusOk(BaseModel):
    """Respuesta mínima de una mutación sin payload propio."""

    status: str


class CreatedId(BaseModel):
    """Respuesta de creación con el id asignado."""

    id: int


class TotalCount(BaseModel):
    """Conteo agregado sin items (previews, badges)."""

    total: int


class DetailMessage(BaseModel):
    """Mensaje informativo de una operación (misma clave que los errores HTTP)."""

    detail: str


class SessionsRevoked(BaseModel):
    """Resultado de revocar sesiones (logout-all, borrado de cuenta)."""

    status: str
    sessions_revoked: int


class StatusMessage(BaseModel):
    """Mutación con mensaje legible además del status."""

    status: str
    message: str
