"""Un lote de eventos de contrato corre en una sola transacción, abierta en ``db/``.

``services.contract_events`` ya no abre conexiones (ratchet TID251, ADR-022):
delega en ``db.contrato_eventos.en_transaccion``. Estos tests sustituyen
``connect`` por uno falso para comprobar, sin Postgres, que la misma conexión
llega a la lectura del historial y a la escritura de eventos, y que el cursor
solo avanza si la transacción terminó bien.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import pytest

from services import contract_events

if TYPE_CHECKING:
    from collections.abc import Iterator

_FILA = {
    "id": 11,
    "id_externo": "EXP-1",
    "captured_at": "2026-11-01T10:00:00",
    "snapshot_json": json.dumps({"importe": 100.0}),
    "changed_fields": "importe",
}


class _Lote:
    """``connect`` falso y las funciones de ``db/`` del lote, anotando con qué conexión se llaman."""

    def __init__(self) -> None:
        self.conexiones: list[object] = []
        self.salidas: list[BaseException | None] = []
        self.usadas: list[tuple[str, object]] = []
        self.cursores: list[str] = []

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
def lote(monkeypatch: pytest.MonkeyPatch) -> _Lote:
    falso = _Lote()
    monkeypatch.setattr("db.contrato_eventos.connect", falso.connect)
    monkeypatch.setattr(contract_events, "get_cursor", lambda _source: {"last_entry_id": "10"})
    monkeypatch.setattr(
        contract_events,
        "set_cursor",
        lambda _source, *, last_entry_id: falso.cursores.append(last_entry_id),
    )
    monkeypatch.setattr(contract_events, "seguidores_de_licitacion", lambda _id: [])

    def _historial(conn: object, after_id: int, limit: int) -> list[dict[str, Any]]:
        falso.usadas.append(("historial", conn))
        return [_FILA] if after_id == 10 else []

    def _estado(conn: object, _id: str) -> dict[str, Any]:
        falso.usadas.append(("estado", conn))
        return {"importe": 150.0}

    monkeypatch.setattr(contract_events, "historial_pendiente", _historial)
    monkeypatch.setattr(contract_events, "estado_actual", _estado)
    return falso


def test_el_lote_usa_una_transaccion_y_avanza_el_cursor_al_final(
    lote: _Lote, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        contract_events,
        "insertar_evento",
        lambda conn, **kw: lote.usadas.append((kw["tipo"], conn)),
    )

    assert contract_events.derive_new_events() == 1

    assert len(lote.conexiones) == 1
    assert lote.salidas == [None]
    assert [nombre for nombre, _ in lote.usadas] == ["historial", "estado", "modificacion"]
    assert {conn for _, conn in lote.usadas} == {lote.conexiones[0]}
    assert lote.cursores == ["11"]


def test_un_fallo_a_mitad_revierte_y_no_mueve_el_cursor(
    lote: _Lote, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _falla(_conn: object, **_kw: Any) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(contract_events, "insertar_evento", _falla)

    with pytest.raises(RuntimeError, match="boom"):
        contract_events.derive_new_events()

    assert len(lote.salidas) == 1
    assert isinstance(lote.salidas[0], RuntimeError)
    assert lote.cursores == []


def test_sin_historial_pendiente_no_toca_el_cursor(
    lote: _Lote, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(contract_events, "get_cursor", lambda _source: {"last_entry_id": "99"})

    assert contract_events.derive_new_events() == 0
    assert lote.cursores == []
