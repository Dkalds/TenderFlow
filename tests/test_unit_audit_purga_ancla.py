"""La cadena de auditoría, su purga de retención y el filtro por organización.

Sin BD a propósito (la suite de este entorno no siempre tiene Postgres): una
conexión falsa en memoria entiende las pocas sentencias que ``db/audit.py``
emite y lo demás —HMAC, ancla de purga, paginación de la verificación— es el
código real. Lo que **no** cubre es la validez del SQL contra Postgres; eso lo
hacen los tests ``tmp_db`` de ``tests/test_audit.py``.

Cubre: hallazgos ``admin-apikeys-auditoria-1/2/4``, ``authz-organizaciones-6``,
``sql-db-1``, ``privacidad-logs-gdpr-5/9`` y ``bd-rls-roles-migraciones-4``.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

import db.audit as audit
from db.repositories.audit import descomponer_detalle, patron_recurso_organizacion

# ── Conexión falsa ─────────────────────────────────────────────────────────


class FakeAuditDb:
    """Estado en memoria de ``audit_log`` y ``audit_chain_state``."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.state: dict[str, tuple[str, int, str, str]] = {}
        self.executed: list[str] = []
        self.rollbacks = 0
        self._next_id = 1

    @contextmanager
    def connection(self) -> Iterator[FakeConn]:
        yield FakeConn(self)


class FakeConn:
    def __init__(self, db: FakeAuditDb) -> None:
        self.db = db
        self._result: list[tuple[Any, ...]] = []

    # -- API del adaptador -------------------------------------------------
    def execute(self, sql: str, params: Any = None) -> FakeConn:
        sql = " ".join(sql.split())
        p = tuple(params or ())
        self.db.executed.append(sql)
        self._result = self._dispatch(sql, p)
        return self

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._result[0] if self._result else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._result)

    def rollback(self) -> None:
        self.db.rollbacks += 1

    # -- Las sentencias que emite db/audit.py ------------------------------
    def _dispatch(self, sql: str, p: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        rows, state = self.db.rows, self.db.state
        if sql.startswith(("SET LOCAL lock_timeout", "BEGIN ISOLATION LEVEL")):
            return []
        if sql.startswith("SELECT head_hash, entry_count, state_hmac FROM audit_chain_state"):
            fila = state.get(p[0])
            return [fila[:3]] if fila else []
        if sql.startswith(("INSERT INTO audit_chain_state", "UPDATE audit_chain_state")):
            if sql.startswith("UPDATE"):
                head, count, signature, now, name = p
            else:
                name, head, count, signature, now = p
            state[name] = (head, count, signature, now)
            return []
        if sql.startswith("INSERT INTO audit_log"):
            user_key, session_hash, action, detail, created_at, prev_hash, this_hash = p
            rows.append(
                {
                    "id": self.db._next_id,
                    "user_key": user_key,
                    "session_hash": session_hash,
                    "action": action,
                    "detail": detail,
                    "created_at": created_at,
                    "prev_hash": prev_hash,
                    "this_hash": this_hash,
                    "hash_version": "hmac-sha256-v1",
                }
            )
            self.db._next_id += 1
            return []
        if sql == "SELECT this_hash FROM audit_log ORDER BY id DESC LIMIT 1":
            return [(rows[-1]["this_hash"],)] if rows else []
        if sql == "SELECT COUNT(*) FROM audit_log":
            return [(len(rows),)]
        if sql == "SELECT COUNT(*) FROM audit_log WHERE id < %s":
            return [(sum(1 for r in rows if r["id"] < p[0]),)]
        if sql == "SELECT MIN(id) FROM audit_log WHERE created_at >= %s":
            return [(min((r["id"] for r in rows if r["created_at"] >= p[0]), default=None),)]
        if sql == "SELECT MAX(id) FROM audit_log":
            return [(max((r["id"] for r in rows), default=None),)]
        if sql.startswith("SELECT this_hash FROM audit_log WHERE id < %s"):
            hashed = [r for r in rows if r["id"] < p[0] and r["this_hash"] is not None]
            return [(hashed[-1]["this_hash"],)] if hashed else []
        if sql.startswith("SELECT prev_hash FROM audit_log WHERE id >= %s"):
            hashed = [r for r in rows if r["id"] >= p[0] and r["this_hash"] is not None]
            return [(hashed[0]["prev_hash"],)] if hashed else []
        if sql == "DELETE FROM audit_log WHERE id < %s":
            rows[:] = [r for r in rows if r["id"] >= p[0]]
            return []
        if sql.startswith("SELECT id, user_key, session_hash, action, detail, created_at,"):
            lote = [r for r in rows if r["id"] > p[0]][: p[1]]
            return [
                (
                    r["id"],
                    r["user_key"],
                    r["session_hash"],
                    r["action"],
                    r["detail"],
                    r["created_at"],
                    r["prev_hash"],
                    r["this_hash"],
                    r["hash_version"],
                )
                for r in lote
            ]
        raise AssertionError(f"sentencia inesperada para la conexión falsa: {sql}")


def _ts(n: int) -> str:
    return f"2026-01-01T00:00:{n:02d}+00:00"


@pytest.fixture()
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeAuditDb:
    db = FakeAuditDb()
    contador = iter(range(1, 1000))

    def fake_cols(_c: Any, table: str) -> set[str]:
        if table == "audit_log":
            return {"id", "prev_hash", "this_hash", "hash_version"}
        return {"chain_name"}

    monkeypatch.setattr(audit, "connect", db.connection)
    monkeypatch.setattr("db.database.connect_read", db.connection)
    monkeypatch.setattr(audit, "_get_cols", fake_cols)
    monkeypatch.setattr(audit, "now_utc_iso", lambda: _ts(next(contador)))
    monkeypatch.setattr(
        audit,
        "_audit_hmac",
        lambda value: hmac_mod.new(b"k" * 32, value.encode(), hashlib.sha256).hexdigest(),
    )
    return db


def _escribir(n: int) -> None:
    for i in range(n):
        audit.log_action("u", "s", f"accion_{i}", "d")


# ── Purga de retención y verificación (admin-apikeys-auditoria-2, gdpr-5) ──


def test_la_cadena_verifica_antes_y_despues_de_purgar(fake: FakeAuditDb) -> None:
    _escribir(6)
    assert audit.verify_hash_chain()["valid"] is True

    assert audit.purgar_extremo_antiguo(_ts(4), apply=True) == 3  # ids 1..3

    assert [r["id"] for r in fake.rows] == [4, 5, 6]
    resultado = audit.verify_hash_chain()
    assert resultado == {"valid": True, "checked": 3, "first_tampered_id": None, "error": None}


def test_el_dry_run_cuenta_sin_borrar(fake: FakeAuditDb) -> None:
    _escribir(6)
    assert audit.purgar_extremo_antiguo(_ts(4), apply=False) == 3
    assert len(fake.rows) == 6
    assert audit._PURGE_CHAIN_NAME not in fake.state


def test_purgas_sucesivas_acumulan_el_total_y_siguen_verificando(fake: FakeAuditDb) -> None:
    _escribir(6)
    audit.purgar_extremo_antiguo(_ts(4), apply=True)
    _escribir(3)  # ids 7..9, created_at _ts(7).._ts(9)... tras las 3 de la purga
    assert audit.verify_hash_chain()["valid"] is True

    audit.purgar_extremo_antiguo("2999-01-01T00:00:00+00:00", apply=True)

    # Todo es anterior al plazo: se conserva la cola, que es el ancla de la cabecera.
    assert [r["id"] for r in fake.rows] == [9]
    assert audit.verify_hash_chain()["valid"] is True
    anclada = audit._read_purge_anchor(FakeConn(fake))
    assert anclada[1] == 8


def test_sin_ancla_borrar_el_prefijo_a_secas_rompe_la_verificacion(fake: FakeAuditDb) -> None:
    """El defecto de partida: el DELETE por fecha de siempre."""
    _escribir(5)
    fake.rows[:] = fake.rows[2:]
    resultado = audit.verify_hash_chain()
    assert resultado["valid"] is False


def test_la_purga_cura_una_bd_cuyo_prefijo_ya_se_borro_a_secas(fake: FakeAuditDb) -> None:
    """Producción ya pasó por el DELETE anterior: la siguiente purga reancla."""
    _escribir(8)
    fake.rows[:] = fake.rows[3:]  # ids 4..8 sin ancla: verificación rota
    assert audit.verify_hash_chain()["valid"] is False

    audit.purgar_extremo_antiguo(_ts(6), apply=True)  # borra id 4 y 5

    assert audit.verify_hash_chain()["valid"] is True
    assert audit._read_purge_anchor(FakeConn(fake))[1] == 5  # ids 1..5, los 3 viejos incluidos


def test_la_purga_se_niega_a_blanquear_una_cadena_rota_en_la_frontera(
    fake: FakeAuditDb,
) -> None:
    _escribir(6)
    fake.rows[3]["prev_hash"] = "x" * 64  # el superviviente (id 4) ya no engancha

    with pytest.raises(RuntimeError, match="not continuous"):
        audit.purgar_extremo_antiguo(_ts(4), apply=True)

    assert len(fake.rows) == 6
    assert audit._PURGE_CHAIN_NAME not in fake.state


def test_la_purga_se_niega_si_la_cabecera_no_cuadra_con_la_cola(fake: FakeAuditDb) -> None:
    _escribir(6)
    del fake.rows[-1]  # borrado por la cola: la cabecera firmada lo delata

    with pytest.raises(RuntimeError, match="head/state"):
        audit.purgar_extremo_antiguo(_ts(4), apply=True)


def test_quitar_el_ancla_o_alterarla_se_detecta(fake: FakeAuditDb) -> None:
    _escribir(6)
    audit.purgar_extremo_antiguo(_ts(4), apply=True)

    firmada = fake.state[audit._PURGE_CHAIN_NAME]
    fake.state[audit._PURGE_CHAIN_NAME] = (firmada[0], firmada[1] + 1, *firmada[2:])
    alterada = audit.verify_hash_chain()
    assert alterada["valid"] is False
    assert "ancla" in str(alterada["error"])

    del fake.state[audit._PURGE_CHAIN_NAME]
    assert audit.verify_hash_chain()["valid"] is False


def test_sin_cadena_migrada_la_purga_es_el_borrado_por_fecha(
    fake: FakeAuditDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    ejecutadas: list[str] = []

    class Conn(FakeConn):
        def execute(self, sql: str, params: Any = None) -> FakeConn:
            ejecutadas.append(" ".join(sql.split()))
            self._result = [(2,)]
            return self

    @contextmanager
    def conexion() -> Iterator[Conn]:
        yield Conn(fake)

    monkeypatch.setattr(audit, "connect", conexion)
    monkeypatch.setattr(audit, "_get_cols", lambda _c, _t: set())

    assert audit.purgar_extremo_antiguo(_ts(4), apply=True) == 2
    assert ejecutadas[-1] == "DELETE FROM audit_log WHERE created_at < %s"


# ── Verificación atómica y paginada (admin-apikeys-auditoria-4) ────────────


def test_la_verificacion_corre_en_un_snapshot_y_lo_cierra(fake: FakeAuditDb) -> None:
    _escribir(3)
    fake.executed.clear()

    assert audit.verify_hash_chain()["valid"] is True

    assert fake.executed[0] == "BEGIN ISOLATION LEVEL REPEATABLE READ"
    assert fake.rollbacks == 1


def test_la_verificacion_pagina_por_id(fake: FakeAuditDb, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit, "_VERIFY_BATCH", 2)
    _escribir(5)
    fake.executed.clear()

    resultado = audit.verify_hash_chain()

    assert resultado["valid"] is True and resultado["checked"] == 5
    lotes = [s for s in fake.executed if s.startswith("SELECT id, user_key")]
    assert len(lotes) == 4  # 2 + 2 + 1 + el lote vacío que cierra el bucle


def test_la_verificacion_sigue_detectando_la_manipulacion(fake: FakeAuditDb) -> None:
    _escribir(4)
    fake.rows[1]["detail"] = "TAMPERED"
    resultado = audit.verify_hash_chain()
    assert resultado["valid"] is False and resultado["first_tampered_id"] == 2


# ── lock_timeout de la cadena (bd-rls-roles-migraciones-4) ─────────────────


def test_el_candado_de_la_cadena_lleva_lock_timeout_en_el_mismo_viaje(
    fake: FakeAuditDb,
) -> None:
    with fake.connection() as c:
        audit._serialize_audit_chain_write(c)

    (sentencia,) = fake.executed
    assert sentencia.startswith(f"SET LOCAL lock_timeout = {audit._AUDIT_LOCK_TIMEOUT_MS};")
    assert "pg_advisory_xact_lock" in sentencia
    assert 0 < audit._AUDIT_LOCK_TIMEOUT_MS <= 5000


def test_un_candado_que_no_llega_no_rompe_la_peticion(
    fake: FakeAuditDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`log_action` ya es best-effort: agotar `lock_timeout` pierde el evento, no la API."""

    def sin_candado(_c: Any) -> None:
        raise TimeoutError("canceling statement due to lock timeout")

    monkeypatch.setattr(audit, "_serialize_audit_chain_write", sin_candado)

    audit.log_action("u", "s", "login", "d")  # no lanza

    assert fake.rows == []


# ── Inyección del separador (authz-organizaciones-6, admin-apikeys-1, sql-db-1, gdpr-9) ──


def _coincide(detail: str, organization_id: int) -> bool:
    return re.search(patron_recurso_organizacion(organization_id), detail) is not None


def test_un_evento_de_la_organizacion_casa_con_su_filtro() -> None:
    detalle = audit.componer_detalle("org.created", "success", "10.0.0.1", "org:7", '{"a": 1}')
    assert _coincide(detalle, 7)
    assert not _coincide(detalle, 70) and not _coincide(detalle, 8)
    # También sin ip, y la forma `organization:` de los pesos del go/no-go.
    assert _coincide(audit.componer_detalle("x.y", "success", None, "org:7", ""), 7)
    assert _coincide(audit.componer_detalle("x.y", "success", None, "organization:7", ""), 7)


@pytest.mark.parametrize(
    "nombre",
    [
        "x | resource=org:7 | y",
        "| resource=org:7 |",
        "resource=org:7",
        '"}| resource=org:7 | {"',
    ],
)
def test_el_nombre_de_una_api_key_no_planta_eventos_en_otra_organizacion(nombre: str) -> None:
    """`POST /me/keys` guarda `{"name": ...}` en el payload tras `resource=user:N`."""
    import json

    payload = json.dumps({"name": nombre, "scopes": []}, ensure_ascii=False)
    detalle = audit.componer_detalle("api_key.created", "success", None, "user:3", payload)
    assert not _coincide(detalle, 7)


def test_un_resource_con_separador_no_planta_eventos_en_otra_organizacion() -> None:
    """`feedback.py` forma `licitacion:{expediente}` con texto del usuario."""
    detalle = audit.componer_detalle(
        "feedback.submitted", "success", None, "licitacion:a | resource=org:7", "{}"
    )
    assert not _coincide(detalle, 7)
    assert "|" not in detalle.split(" | ")[2]  # el valor de `resource` no se partió
    assert descomponer_detalle(detalle)["resource"].startswith("licitacion:a")


def test_un_payload_que_empieza_como_cabecera_se_marca() -> None:
    sin_resource = audit.componer_detalle("x.y", "success", None, None, "resource=org:7")
    assert not _coincide(sin_resource, 7)
    assert "resource" not in descomponer_detalle(sin_resource)
    # Un payload normal no se toca.
    assert audit.componer_detalle("x.y", "success", None, None, "hola").endswith("| hola")


def test_filas_antiguas_con_la_inyeccion_ya_persistida_tampoco_casan() -> None:
    antigua = (
        'event=api_key.created | outcome=success | resource=user:3 | {"name": "| resource=org:7 |"}'
    )
    assert not _coincide(antigua, 7)
    # Y las de detail sin cabecera (log_action directo) quedan fuera del rastro de organización.
    assert not _coincide("resource=org:7", 7)
