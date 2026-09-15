"""Organización activa de la petición en curso (contexto de tenencia).

Es la mitad «aplicación» del aislamiento en dos capas de ADR-034: la capa
primaria siguen siendo los repositorios, que filtran por ``organization_id``;
la segunda es una política RLS por tenant en Postgres (``v128``) que lee la
variable de transacción ``app.organization_id``. Este módulo es el puente
entre ambas: ``api/tenancy.py`` fija aquí la organización resuelta y
``db/connection.py`` la lee al abrir cada transacción para emitir el ``SET
LOCAL`` correspondiente.

Se apoya en :mod:`contextvars` y no en un global ni en un thread-local:

- Cada petición de FastAPI corre en su propia tarea de asyncio, y una tarea
  nueva recibe una **copia** del contexto — lo que una petición fije nunca lo
  ve otra, aunque compartan hilo.
- ``anyio.to_thread.run_sync`` (lo que hay debajo de ``api.concurrency.run_db``)
  copia el contexto de la tarea al hilo del pool, así que el valor llega al
  código síncrono que abre la conexión. ``tests/test_tenant_context.py`` fija
  esa propagación; si un día anyio dejara de copiarlo, ``run_db`` tendría
  que hacerlo con ``contextvars.copy_context().run``.

Sin ámbito fijado (scheduler, scripts, migraciones, tests sin scope) todo
sigue funcionando como hasta ahora: ``current_organization()`` devuelve
``None`` y la conexión no emite nada.

Puro: sin I/O ni dependencias del resto del proyecto, para que ``db/`` pueda
importarlo sin arrastrar ``api/``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

_organization_id: ContextVar[int | None] = ContextVar("tenant_organization_id", default=None)


def _validar(organization_id: int | None) -> int | None:
    """Acepta un entero positivo o ``None`` (sin ámbito).

    El valor acaba interpolado como literal en un ``SET LOCAL`` (``db/connection.py``),
    así que se rechaza aquí cualquier cosa que no sea un entero de verdad —
    incluido ``bool``, que es subclase de ``int`` y pasaría un ``isinstance``.
    """
    if organization_id is None:
        return None
    if isinstance(organization_id, bool) or not isinstance(organization_id, int):
        raise TypeError(f"organization_id debe ser int, no {type(organization_id).__name__}")
    if organization_id < 1:
        raise ValueError(f"organization_id debe ser positivo: {organization_id}")
    return organization_id


def set_organization(organization_id: int | None) -> Token[int | None]:
    """Fija la organización activa y devuelve el token para ``reset_organization``.

    ``None`` limpia el ámbito de forma explícita (útil para una operación
    legítimamente transversal dentro de una petición ya acotada).
    """
    return _organization_id.set(_validar(organization_id))


def reset_organization(token: Token[int | None]) -> None:
    """Restaura el valor previo a la llamada que produjo ``token``."""
    _organization_id.reset(token)


def current_organization() -> int | None:
    """Organización activa, o ``None`` si nadie fijó ámbito en este contexto."""
    return _organization_id.get()


@contextmanager
def tenant_scope(organization_id: int | None) -> Iterator[None]:
    """Acota un bloque a ``organization_id`` y restaura el ámbito anterior al salir.

    Uso::

        with tenant_scope(organization_id):
            rows = repo.list_scoped(organization_id)
    """
    token = set_organization(organization_id)
    try:
        yield
    finally:
        reset_organization(token)


__all__ = [
    "current_organization",
    "reset_organization",
    "set_organization",
    "tenant_scope",
]
