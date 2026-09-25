"""``GET /notifications``: un salto al threadpool, una conexión y un ámbito.

Sin BD. Las cinco lecturas del handler se sustituyen por dobles que leen de
verdad a través de ``db.connection.connect_read`` —así pasan por la
agrupación real de ``lecturas_agrupadas``— y ``_get_conn`` por un doble que
cuenta checkouts y registra lo que se ejecuta. Lo que se fija:

- un único ``run_db``;
- un único checkout del pool de lectura para las cinco lecturas;
- un único ``BEGIN; SET LOCAL`` con la organización y un único ``ROLLBACK``;
- la respuesta sale igual que antes.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

import db.connection as conn_mod
from api.routes import notifications as ruta
from shared.tenant_context import tenant_scope


class _Raw:
    """Conexión psycopg de mentira: registra sentencias y lleva el estado de la transacción."""

    def __init__(self, registro: list[str]) -> None:
        from psycopg.pq import TransactionStatus

        self._registro = registro
        self._estados = TransactionStatus
        self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)

    def execute(self, sql: str, params: Any = None) -> Any:
        self._registro.append(sql)
        if sql.startswith("BEGIN"):
            self.info.transaction_status = self._estados.INTRANS
        return self

    def cursor(self) -> _Cursor:
        return _Cursor(self._registro)

    def rollback(self) -> None:
        self._registro.append("ROLLBACK")
        self.info.transaction_status = self._estados.IDLE

    def commit(self) -> None:
        self._registro.append("COMMIT")


class _Cursor:
    def __init__(self, registro: list[str]) -> None:
        self._registro = registro
        self.description = None
        self.rowcount = 0

    def execute(self, sql: str, params: Any = None) -> None:
        self._registro.append(sql)

    def fetchone(self) -> Any:
        return None

    def fetchall(self) -> list[Any]:
        return []


@pytest.fixture()
def pool(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    estado: dict[str, Any] = {"checkouts": 0, "devoluciones": 0, "registro": []}

    def _get_conn(*, read_only: bool = False) -> conn_mod._PgConnAdapter:
        assert read_only, "este handler solo lee"
        estado["checkouts"] += 1
        return conn_mod._PgConnAdapter(_Raw(estado["registro"]), pool=None)

    def _return_conn(_conn: Any) -> None:
        estado["devoluciones"] += 1

    monkeypatch.setattr(conn_mod, "_get_conn", _get_conn)
    monkeypatch.setattr(conn_mod, "_return_conn", _return_conn)
    return estado


def _lectura(nombre: str, llamadas: list[str]) -> None:
    """Una lectura real por ``connect_read``: la que agruparía el handler."""
    assert conn_mod._lectura_agrupada.get() is not None, f"{nombre} corrió fuera del grupo"
    llamadas.append(nombre)
    with conn_mod.connect_read() as c:
        c.execute(f"SELECT {nombre}")


@pytest.fixture()
def lecturas(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    llamadas: list[str] = []
    muestra = [
        SimpleNamespace(id_externo="L-1", titulo="Uno", importe=10.0, organo_contratacion="A"),
        SimpleNamespace(id_externo="L-2", titulo="Dos", importe=None, organo_contratacion="B"),
    ]

    def _novedades(user_id: int) -> Any:
        _lectura("novedades", llamadas)
        return SimpleNamespace(sample=muestra)

    def _hoy(_filters: Any) -> Any:
        _lectura("hoy", llamadas)
        contadores = {"calientes": 1, "vencen_48h": 2, "nuevas_24h": 3, "total_activas": 4}
        return SimpleNamespace(model_dump=lambda: contadores)

    def _no_leidas(user_key: str, ids: list[str], *, user_id: int | None) -> list[str]:
        _lectura("no_leidas", llamadas)
        return ids[:1]

    def _alertas(user_key: str, limit: int, org: int, *, user_id: int | None) -> list[dict]:
        _lectura("alertas", llamadas)
        return [{"id": 9, "type": "regla", "title": "t", "read_at": None, "pursuit_id": 3}]

    def _alertas_sin_leer(user_key: str, org: int, *, user_id: int | None) -> int:
        _lectura("alertas_sin_leer", llamadas)
        return 1

    monkeypatch.setattr(ruta, "get_resumen_novedades", _novedades)
    monkeypatch.setattr(ruta, "get_resumen_hoy", _hoy)
    monkeypatch.setattr(ruta, "get_unread_ids", _no_leidas)
    monkeypatch.setattr(ruta, "get_user_alerts", _alertas)
    monkeypatch.setattr(ruta, "get_alerts_unread_count", _alertas_sin_leer)
    return llamadas


def test_cinco_lecturas_un_run_db_una_conexion_un_ambito(
    pool: dict[str, Any], lecturas: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    saltos = {"n": 0}
    run_db_real = ruta.run_db

    async def _run_db_contado(fn: Any, *args: Any, **kwargs: Any) -> Any:
        saltos["n"] += 1
        return await run_db_real(fn, *args, **kwargs)

    monkeypatch.setattr(ruta, "run_db", _run_db_contado)
    ctx = {"user_id": 5, "user_key": "uk-5", "organization_id": 7}

    with tenant_scope(7):
        resultado = asyncio.run(ruta.get_notifications(ctx=ctx))

    assert lecturas == ["novedades", "hoy", "no_leidas", "alertas", "alertas_sin_leer"]
    assert saltos["n"] == 1
    assert pool["checkouts"] == 1
    assert pool["devoluciones"] == 1
    registro = pool["registro"]
    assert registro[0] == "BEGIN; SET LOCAL app.organization_id = '7'"
    assert registro.count(registro[0]) == 1, "el ámbito se abre una sola vez"
    assert registro[-1] == "ROLLBACK"
    assert registro.count("ROLLBACK") == 1
    # Una consulta por lectura: 1 + 5 + 1 viajes.
    assert len(registro) == 7

    assert [i.id for i in resultado.items] == ["L-1", "L-2"]
    assert [i.read for i in resultado.items] == [False, True]
    assert resultado.unread_count == 1
    assert resultado.alerts[0].pursuit_id == 3
    assert resultado.alerts_unread_count == 1
    assert resultado.hoy.total_activas == 4


def test_sin_usuario_no_pide_novedades(pool: dict[str, Any], lecturas: list[str]) -> None:
    ctx = {"user_id": None, "user_key": "uk-x", "organization_id": 7}

    with tenant_scope(7):
        resultado = asyncio.run(ruta.get_notifications(ctx=ctx))

    assert "novedades" not in lecturas
    assert resultado.items == []
    assert pool["checkouts"] == 1
