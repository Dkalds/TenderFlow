"""Las lecturas simples de ``db/`` van por el pool de lectura, no por el de escritura.

Sin BD: ``connect`` de cada módulo se sustituye por uno que falla y
``connect_read`` por un doble que responde vacío. Fija **por dónde** va cada
consulta (un viaje en autocommit en vez de ``BEGIN`` + consulta + ``COMMIT``);
la semántica la cubren los tests de cada módulo contra Postgres.

Las que se quedan en ``connect()`` lo hacen a propósito (leen justo después de
una escritura de la misma petición o deciden una escritura idempotente) y no
están aquí: ``feature_flags.list_flags``, ``users.is_admin``,
``users.admin_granted_by``, ``events.get_events``,
``events.agregados_con_evento``, ``dlq.list_unresolved``,
``watchlist.list_entries_por_clave``, ``watchlist.entradas_por_id`` y
``saved_filters.list_saved_filters``.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest


class _ConexionVacia:
    rowcount = 0

    def __init__(self, registro: list[str]) -> None:
        self._registro = registro
        self.description: list[tuple[str]] = []

    def execute(self, sql: str, params: Any = None) -> _ConexionVacia:
        self._registro.append(sql)
        return self

    def fetchone(self) -> None:
        return None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return []


_LECTURAS: list[tuple[str, str, Callable[[Any], Any]]] = [
    ("db.feature_flags", "is_enabled", lambda f: f("flag", "ana@example.com")),
    ("db.feature_flags", "get_flag", lambda f: f("flag")),
    ("db.users", "get_user_by_email", lambda f: f("ana@example.com")),
    ("db.users", "get_users_by_email_ci", lambda f: f("ana@example.com")),
    ("db.users", "get_active_user_by_email_ci", lambda f: f("ana@example.com")),
    ("db.users", "list_users", lambda f: f()),
    ("db.sessions", "validate_session", lambda f: f("token")),
    ("db.sessions", "list_active_sessions", lambda f: f(7)),
    ("db.events", "get_events_by_type", lambda f: f("feedback.submitted")),
    ("db.dlq", "count_unresolved", lambda f: f()),
    ("db.dlq", "list_exhausted", lambda f: f()),
    ("db.dlq", "get_failure", lambda f: f(1)),
    ("db.dlq", "unresolved_summary", lambda f: f()),
    ("db.dlq", "unresolved_error_summary", lambda f: f()),
    ("db.watchlist", "list_entries", lambda f: f(7)),
    ("db.watchlist", "list_entries", lambda f: f(7, organization_id=3)),
    ("db.saved_filters", "list_own_saved_filters", lambda f: f(user_id=7)),
]


@pytest.mark.parametrize(
    ("modulo", "funcion", "llamar"),
    _LECTURAS,
    ids=[f"{m.removeprefix('db.')}.{f}" for m, f, _ in _LECTURAS],
)
def test_la_lectura_va_por_el_pool_de_lectura(
    monkeypatch: pytest.MonkeyPatch,
    modulo: str,
    funcion: str,
    llamar: Callable[[Any], Any],
) -> None:
    mod = importlib.import_module(modulo)
    lecturas: list[str] = []

    @contextmanager
    def _lectura(**_kw: Any) -> Iterator[_ConexionVacia]:
        yield _ConexionVacia(lecturas)

    @contextmanager
    def _escritura() -> Iterator[_ConexionVacia]:
        raise AssertionError(f"{modulo}.{funcion} abrió el pool de escritura")
        yield  # pragma: no cover - el generador nunca llega aquí

    monkeypatch.setattr(mod, "connect", _escritura)
    monkeypatch.setattr(mod, "connect_read", _lectura, raising=False)

    llamar(getattr(mod, funcion))

    assert lecturas, f"{modulo}.{funcion} no consultó por el pool de lectura"
