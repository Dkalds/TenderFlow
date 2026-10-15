"""Revocación manual de los tokens OAuth del MCP (``scripts/mcp_revocar.py``).

Corta el acceso de una cuenta sin esperar a que caduque su access token: es la
palanca del operador cuando se pierde un portátil o se va alguien. Se fija que
el script revoca todo lo vivo, deja rastro en ``audit_log`` y sale con 1 si el
correo no existe.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from db.connection import connect_read, now_utc
from db.mcp_oauth import TipoToken, guardar_cliente, guardar_token, obtener_token
from db.users import create_user
from scripts.mcp_revocar import main

EMAIL = "admin@example.com"


@pytest.fixture()
def usuario_con_dos_tokens(tmp_db: Any) -> tuple[int, str]:
    guardar_cliente("cli", "Claude", ["https://claude.ai/api/mcp/auth_callback"], {})
    uid = create_user(email=EMAIL, password_hash="x")  # pragma: allowlist secret
    tokens: list[tuple[str, TipoToken]] = [("acc-en-claro", "access"), ("ref-en-claro", "refresh")]
    for token, kind in tokens:
        guardar_token(
            token,
            kind=kind,
            client_id="cli",
            user_id=uid,
            family_id="fam-1",
            scopes=["mcp:read"],
            datos=None,
            expires_at=now_utc() + timedelta(hours=1),
        )
    return uid, "acc-en-claro"


def test_revocar_usuario_inexistente_sale_con_1(
    tmp_db: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--email", "nadie@x.es"]) == 1
    assert "nadie@x.es" in capsys.readouterr().err
    assert _auditoria() == []


def test_revocar_cuenta_y_audita(
    usuario_con_dos_tokens: tuple[int, str], capsys: pytest.CaptureFixture[str]
) -> None:
    uid, acceso = usuario_con_dos_tokens
    assert obtener_token(acceso, "access") is not None

    assert main(["--email", EMAIL]) == 0

    assert f"Revocados 2 tokens de {EMAIL}" in capsys.readouterr().out
    assert obtener_token(acceso, "access") is None  # caducado o revocado == inexistente
    filas = _auditoria()
    assert len(filas) == 1
    assert filas[0][0] == uid
    assert '"revocados": 2' in filas[0][1]


def test_revocar_dos_veces_la_segunda_cierra_cero(
    usuario_con_dos_tokens: tuple[int, str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--email", EMAIL]) == 0
    capsys.readouterr()
    assert main(["--email", EMAIL]) == 0
    assert f"Revocados 0 tokens de {EMAIL}" in capsys.readouterr().out


def _auditoria() -> list[tuple[Any, ...]]:
    with connect_read() as c:
        return [
            tuple(f)
            for f in c.execute(
                "SELECT user_id, detail FROM audit_log WHERE action = 'mcp.revocacion_manual'"
            ).fetchall()
        ]
