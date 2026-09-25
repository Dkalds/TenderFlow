"""La validación de sesión lee por el pool de lectura y escribe solo cuando toca.

Sin BD: ``connect_read`` y ``connect`` de ``db.sessions`` se sustituyen por
dobles que registran qué se ejecuta en cada uno. La semántica —revocada,
caducada, techo absoluto, usuario desactivado, renovación con throttle— la
cubren contra Postgres ``tests/test_sessions_principal.py`` y
``tests/test_sessions_deslizantes.py``; aquí se fija **por dónde** va cada
consulta y cuántas hay.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import db.sessions as sessions


class _Conexion:
    def __init__(
        self, fila: tuple[Any, ...] | None, registro: list[tuple[str, str, Any]], pool: str
    ):
        self._fila = fila
        self._registro = registro
        self._pool = pool

    def execute(self, sql: str, params: Any = None) -> _Conexion:
        self._registro.append((self._pool, " ".join(sql.split()), params))
        return self

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._fila


@pytest.fixture()
def bd(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    estado: dict[str, Any] = {"fila": None, "registro": []}

    @contextmanager
    def _lectura() -> Iterator[_Conexion]:
        yield _Conexion(estado["fila"], estado["registro"], "lectura")

    @contextmanager
    def _escritura() -> Iterator[_Conexion]:
        yield _Conexion(None, estado["registro"], "escritura")

    monkeypatch.setattr(sessions, "connect_read", _lectura)
    monkeypatch.setattr(sessions, "connect", _escritura)
    return estado


def _fila(
    *,
    creada_hace: timedelta = timedelta(hours=1),
    caduca_en: timedelta = timedelta(hours=10),
    visto_hace: timedelta | None = timedelta(seconds=5),
    revocada: int = 0,
    usuario: int | None = 7,
    desactivado: str | None = None,
) -> tuple[Any, ...]:
    ahora = datetime.now(UTC)
    return (
        7,  # user_id
        (ahora - creada_hace).isoformat(),
        (ahora + caduca_en).isoformat(),
        revocada,
        "127.0.0.1",
        (ahora - visto_hace).isoformat() if visto_hace is not None else None,
        None,  # mfa_verified_at
        usuario,
        "ana@example.com",
        "Ana",
        0,  # is_admin
        desactivado,
        0,  # totp confirmado
    )


def _por_pool(registro: list[tuple[str, str, Any]], pool: str) -> list[str]:
    return [sql for p, sql, _ in registro if p == pool]


def test_sesion_valida_y_reciente_es_una_sola_lectura(bd: dict[str, Any]) -> None:
    bd["fila"] = _fila(visto_hace=timedelta(seconds=5))

    principal = sessions.validate_session_principal("token")

    assert principal is not None and principal["id"] == 7
    assert len(_por_pool(bd["registro"], "lectura")) == 1
    assert _por_pool(bd["registro"], "escritura") == [], "dentro del throttle no se escribe"


def test_sesion_con_throttle_vencido_renueva_en_el_pool_de_escritura(bd: dict[str, Any]) -> None:
    bd["fila"] = _fila(visto_hace=timedelta(minutes=5))

    principal = sessions.validate_session_principal("token")

    assert principal is not None
    escrituras = [(sql, params) for p, sql, params in bd["registro"] if p == "escritura"]
    assert len(escrituras) == 1
    sql, params = escrituras[0]
    assert sql.startswith("UPDATE sessions SET last_seen_at")
    # No revive una revocada entre la lectura y la escritura.
    assert "AND revoked = 0" in sql
    # La renovación que devuelve es la misma que escribe.
    assert principal["expires_at"] == params[1]


def test_sin_last_seen_tambien_renueva(bd: dict[str, Any]) -> None:
    bd["fila"] = _fila(visto_hace=None)

    assert sessions.validate_session_principal("token") is not None
    assert len(_por_pool(bd["registro"], "escritura")) == 1


def test_sesion_caducada_se_revoca_en_escritura_y_no_vale(bd: dict[str, Any]) -> None:
    bd["fila"] = _fila(caduca_en=timedelta(minutes=-1))

    assert sessions.validate_session_principal("token") is None
    escrituras = _por_pool(bd["registro"], "escritura")
    assert len(escrituras) == 1
    assert escrituras[0].startswith("UPDATE sessions SET revoked = 1")


def test_sesion_pasado_el_techo_se_revoca_aunque_este_fresca(
    bd: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from config.settings import settings

    monkeypatch.setattr(settings, "SESSION_ABSOLUTE_DAYS", 1)
    bd["fila"] = _fila(creada_hace=timedelta(days=2))

    assert sessions.validate_session_principal("token") is None
    assert _por_pool(bd["registro"], "escritura")[0].startswith("UPDATE sessions SET revoked = 1")


@pytest.mark.parametrize(
    "fila",
    [
        pytest.param(None, id="token-desconocido"),
        pytest.param(_fila(revocada=1), id="revocada"),
        pytest.param(_fila(usuario=None), id="usuario-inexistente"),
        pytest.param(_fila(desactivado="2026-09-01T00:00:00+00:00"), id="usuario-desactivado"),
    ],
)
def test_sesion_invalida_no_escribe_nada(bd: dict[str, Any], fila: tuple[Any, ...] | None) -> None:
    bd["fila"] = fila

    assert sessions.validate_session_principal("token") is None
    assert len(_por_pool(bd["registro"], "lectura")) == 1
    assert _por_pool(bd["registro"], "escritura") == []
