"""Protocolos que definen el contrato entre db y observability.

Las funciones de ``observability`` que necesitan acceder a la BD usan lazy
imports de ``db.database``. Estos protocolos documentan el contrato para
que mypy pueda validar la compatibilidad sin crear dependencias circulares
en tiempo de import.

Uso futuro: inyectar implementaciones concretas en lugar de lazy imports,
facilitando testing y desacoplamiento.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CursorProvider(Protocol):
    """Protocolo para obtener un cursor de ingesta (usado por alertas/healthcheck)."""

    def __call__(self, fuente: str) -> str | None: ...


@runtime_checkable
class ConnectionProvider(Protocol):
    """Protocolo para obtener una conexión a la BD."""

    def __call__(self) -> Any: ...


@runtime_checkable
class RunPersister(Protocol):
    """Protocolo para persistir un extraction_run en la BD (usado por metrics)."""

    def __call__(
        self,
        *,
        entrypoint: str,
        status: str,
        duration_seconds: float,
        licitaciones_nuevas: int,
        licitaciones_actualizadas: int,
        errors: int,
        error_detail: str | None,
    ) -> None: ...


@runtime_checkable
class LicitacionCounter(Protocol):
    """Protocolo para contar licitaciones (usado por prometheus)."""

    def __call__(self) -> int: ...
