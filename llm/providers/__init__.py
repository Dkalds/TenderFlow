"""Proveedores LLM disponibles."""

from __future__ import annotations

# Códigos con los que un proveedor dice «esta credencial no vale». No son
# transitorios —reintentar no los arregla— ni tampoco una respuesta vacía.
AUTH_HTTP_CODES: frozenset[int] = frozenset({401, 403})


class LLMAuthError(RuntimeError):
    """El proveedor rechazó la API key (HTTP 401/403).

    Los providers se tragan el resto de fallos y devuelven un stream vacío, que
    los consumidores ya saben degradar. Una credencial rechazada no es un fallo
    más: se repite idéntica en cada llamada que use esa key, y convertida en
    «respuesta vacía» esconde la causa. El scrape diario estuvo en rojo del
    2026-09-05 al 2026-09-10 con `NVIDIA_API_KEY` devolviendo 401 en todas las
    llamadas, mientras la alerta repetía «El LLM devolvió una respuesta vacía»
    doscientas veces por corrida.
    """

    def __init__(self, *, model: str, status_code: int) -> None:
        self.model = model
        self.status_code = status_code
        super().__init__(
            f"El proveedor rechazó la API key (HTTP {status_code}) para {model}: "
            "la credencial no es válida y hay que rotarla"
        )
