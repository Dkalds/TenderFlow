"""Tools del MCP interno (funciones puras sobre ``db/``; el registro vive en el servidor)."""

from __future__ import annotations

__all__ = ["ErrorHerramienta"]


class ErrorHerramienta(Exception):
    """Error de una tool con un mensaje y una pista aptos para devolver al LLM."""

    def __init__(self, mensaje: str, pista: str | None = None) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.pista = pista
