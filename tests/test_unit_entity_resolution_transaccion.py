"""Un lote de resolución de empresas corre en una sola transacción, abierta en ``db/``.

``services.entity_resolution`` ya no abre conexiones (ratchet TID251, ADR-022):
delega en ``db.empresas.en_transaccion``. Estos tests sustituyen ``connect`` por
uno falso para comprobar, sin Postgres, que el lote abre una única transacción,
que la misma conexión llega a lecturas y escrituras y que un fallo a mitad sale
del context manager (rollback) en vez de tragarse.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import pytest

from db.empresas import EmpresaCaches
from services import entity_resolution
from services.normalization import normalize_company

if TYPE_CHECKING:
    from collections.abc import Iterator

NOMBRE = "ACME SOLUCIONES SL"
EMPRESA_ID = 42
ADJUDICACION_ID = 7


class _Transacciones:
    """``connect`` falso: cuenta las transacciones y anota cómo salió cada una."""

    def __init__(self) -> None:
        self.conexiones: list[object] = []
        self.salidas: list[BaseException | None] = []

    @contextmanager
    def connect(self) -> Iterator[object]:
        conn = object()
        self.conexiones.append(conn)
        try:
            yield conn
        except BaseException as exc:
            self.salidas.append(exc)
            raise
        self.salidas.append(None)


@pytest.fixture()
def transacciones(monkeypatch: pytest.MonkeyPatch) -> _Transacciones:
    falso = _Transacciones()
    monkeypatch.setattr("db.empresas.connect", falso.connect)
    return falso


@pytest.fixture()
def conexiones_usadas(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Sustituye las funciones de ``db.empresas`` del lote y anota con qué conexión las llaman."""
    usadas: dict[str, Any] = {}
    alias = normalize_company(NOMBRE)

    def load_caches(conn: object) -> EmpresaCaches:
        usadas["load_caches"] = conn
        return EmpresaCaches(
            nif={},
            alias={alias: EMPRESA_ID},
            alias_by_length={len(alias): {alias}},
            nif_canonico={EMPRESA_ID: None},
        )

    def pending_review_keys(conn: object) -> set[tuple[str, str]]:
        usadas["pending_review_keys"] = conn
        return set()

    def fetch_unlinked(conn: object, *_: object, **__: object) -> list[dict[str, Any]]:
        usadas["fetch_unlinked"] = conn
        return [{"id": ADJUDICACION_ID, "nombre": NOMBRE, "nif": None, "es_pyme": None}]

    def add_aliases(conn: object, variantes: list[Any]) -> None:
        usadas["add_aliases"] = conn

    def link_adjudicaciones(conn: object, enlaces: list[tuple[int, int]]) -> None:
        usadas["link_adjudicaciones"] = (conn, list(enlaces))

    for nombre, fn in {
        "load_caches": load_caches,
        "pending_review_keys": pending_review_keys,
        "fetch_unlinked": fetch_unlinked,
        "add_aliases": add_aliases,
        "link_adjudicaciones": link_adjudicaciones,
    }.items():
        monkeypatch.setattr(entity_resolution, nombre, fn)
    return usadas


def test_lote_abre_una_sola_transaccion_y_la_cierra_con_commit(
    transacciones: _Transacciones, conexiones_usadas: dict[str, Any]
) -> None:
    stats = entity_resolution.resolve_unlinked_adjudicaciones(fuzzy=False)

    assert len(transacciones.conexiones) == 1
    assert transacciones.salidas == [None]
    assert stats.linked_alias == 1
    assert stats.last_id == ADJUDICACION_ID


def test_lecturas_y_escrituras_del_lote_usan_la_misma_conexion(
    transacciones: _Transacciones, conexiones_usadas: dict[str, Any]
) -> None:
    entity_resolution.resolve_unlinked_adjudicaciones(fuzzy=False)

    (conn,) = transacciones.conexiones
    enlace_conn, enlaces = conexiones_usadas.pop("link_adjudicaciones")
    assert enlace_conn is conn
    assert enlaces == [(EMPRESA_ID, ADJUDICACION_ID)]
    assert all(usada is conn for usada in conexiones_usadas.values())


def test_un_fallo_a_mitad_del_lote_sale_del_context_manager(
    transacciones: _Transacciones,
    conexiones_usadas: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = RuntimeError("fallo al enlazar")

    def link_que_falla(conn: object, enlaces: list[tuple[int, int]]) -> None:
        raise error

    monkeypatch.setattr(entity_resolution, "link_adjudicaciones", link_que_falla)

    with pytest.raises(RuntimeError, match="fallo al enlazar"):
        entity_resolution.resolve_unlinked_adjudicaciones(fuzzy=False)

    assert len(transacciones.conexiones) == 1
    assert transacciones.salidas == [error]
