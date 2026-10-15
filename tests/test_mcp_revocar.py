"""Revocación manual de los tokens OAuth del MCP (``scripts/mcp_revocar.py``).

Corta el acceso de una cuenta sin esperar a que caduque su access token: es la
palanca del operador cuando se pierde un portátil o se va alguien. Se fija que
el script revoca todo lo vivo, deja rastro en ``audit_log`` y sale con 1 si el
correo no existe.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest

from db.connection import connect_read, now_utc
from db.mcp_oauth import TipoToken, guardar_cliente, guardar_token, obtener_token
from db.users import create_user, deactivate_user
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


def _tokens(uid: int, prefijo: str, familia: str) -> None:
    tokens: list[tuple[str, TipoToken]] = [
        (f"{prefijo}-acc", "access"),
        (f"{prefijo}-ref", "refresh"),
    ]
    for token, kind in tokens:
        guardar_token(
            token,
            kind=kind,
            client_id="cli",
            user_id=uid,
            family_id=familia,
            scopes=["mcp:read"],
            datos=None,
            expires_at=now_utc() + timedelta(hours=1),
        )


def test_el_correo_se_compara_sin_distinguir_mayusculas_y_alcanza_cuentas_dadas_de_baja(
    tmp_db: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """El login del MCP compara sin mayúsculas; la revocación, igual.

    ``Ana@Empresa.es`` (guardado así por el alta self-service) se alcanza con
    ``ana@empresa.es``, y también una cuenta desactivada que conserve tokens.
    """
    guardar_cliente("cli", "Claude", ["https://claude.ai/api/mcp/auth_callback"], {})
    mixta = create_user(email="Ana@Empresa.es", password_hash="x")  # pragma: allowlist secret
    baja = create_user(email="ANA@empresa.es", password_hash="x")  # pragma: allowlist secret
    _tokens(mixta, "mixta", "fam-m")
    _tokens(baja, "baja", "fam-b")
    deactivate_user(baja)

    assert main(["--email", "ana@empresa.es"]) == 0

    salida = capsys.readouterr().out
    assert "Revocados 2 tokens de Ana@Empresa.es" in salida
    assert "Revocados 2 tokens de ANA@empresa.es" in salida
    assert obtener_token("mixta-acc", "access") is None
    assert obtener_token("baja-acc", "access") is None
    assert sorted(f[0] for f in _auditoria()) == sorted([mixta, baja])


def test_la_auditoria_no_lleva_el_correo_ni_los_tokens(
    usuario_con_dos_tokens: tuple[int, str],
) -> None:
    assert main(["--email", EMAIL]) == 0
    (fila,) = _auditoria()
    assert json.loads(fila[1]) == {"revocados": 2}
    assert EMAIL not in fila[1]
    assert "en-claro" not in fila[1]


def test_en_prod_sin_clave_de_auditoria_no_revoca_y_sale_con_2(
    usuario_con_dos_tokens: tuple[int, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from pydantic import SecretStr

    from config import settings

    _, acceso = usuario_con_dos_tokens
    monkeypatch.setattr(settings, "ENV", "prod")
    monkeypatch.setattr(settings, "AUDIT_HMAC_KEY", SecretStr(""))

    assert main(["--email", EMAIL]) == 2

    assert "AUDIT_HMAC_KEY" in capsys.readouterr().err
    assert obtener_token(acceso, "access") is not None  # nada revocado
    assert _auditoria() == []


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
