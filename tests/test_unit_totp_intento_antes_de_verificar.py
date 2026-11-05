"""El intento de segundo factor se apunta ANTES de verificar el código.

Con «mirar el bloqueo, verificar, apuntar el fallo», N peticiones en paralelo
pasaban todas el control antes de que se apuntara ninguna y el tope de
``MFA_MAX_FAILURES`` no limitaba nada. Es el mismo arreglo que el login
(``tests/test_unit_login_cuenta_y_bulkhead.py``), en las cuatro rutas que
verifican un código. Sin BD: ``db.rate_limits`` y ``db.totp`` son espías.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException, Response

from api.routes.auth import totp as auth

_MAX = auth.settings.MFA_MAX_FAILURES
_CODIGO = auth.TotpCodeRequest(code="123456")
_USUARIO = {"user_id": 7, "session_token": "t", "mfa_required": False}


class _Espia:
    def __init__(self, bloqueos: list[bool] | None = None) -> None:
        self.eventos: list[tuple[Any, ...]] = []
        self._bloqueos = list(bloqueos or [])

    def is_locked(self, user_id: int, *, max_attempts: int, **_: Any) -> tuple[bool, float]:
        self.eventos.append(("lock", max_attempts))
        return (self._bloqueos.pop(0) if self._bloqueos else False), 10.0

    def record(self, user_id: int, **_: Any) -> int:
        self.eventos.append(("record",))
        return 1

    def clear(self, user_id: int) -> None:
        self.eventos.append(("clear",))

    def verify(self, secret: str, code: str) -> bool:
        self.eventos.append(("verify",))
        return False

    def nombres(self) -> list[str]:
        return [e[0] for e in self.eventos]


Llamada = Callable[[], Coroutine[Any, Any, Any]]

#: ruta → (llamada, ¿el secreto ya está confirmado?)
_RUTAS: dict[str, tuple[Llamada, bool]] = {
    "confirm": (lambda: auth.confirm_totp(_CODIGO, Response(), dict(_USUARIO)), False),
    "verify": (lambda: auth.verify_totp_login(_CODIGO, dict(_USUARIO)), True),
    "recovery-codes": (
        lambda: auth.regenerate_recovery_codes(_CODIGO, Response(), dict(_USUARIO)),
        True,
    ),
    "delete": (lambda: auth.remove_totp(_CODIGO, dict(_USUARIO)), True),
}


def _ejecutar(llamada: Llamada, espia: _Espia, confirmado: bool) -> Any:
    secreto = {"secret": "JBSWY3DPEHPK3PXP", "confirmed": confirmado}  # pragma: allowlist secret
    with (
        patch("db.rate_limits.is_mfa_locked_out", espia.is_locked),
        patch("db.rate_limits.record_failed_mfa", espia.record),
        patch("db.rate_limits.clear_mfa_attempts", espia.clear),
        patch("db.totp.get_totp_secret", return_value=secreto),
        patch("db.totp.verify_totp", espia.verify),
        patch("db.totp.use_recovery_code", return_value=False),
    ):
        try:
            return asyncio.run(llamada())
        except HTTPException as exc:
            return exc


@pytest.mark.parametrize("ruta", sorted(_RUTAS))
def test_el_intento_mfa_se_apunta_antes_de_verificar(ruta: str) -> None:
    llamada, confirmado = _RUTAS[ruta]
    espia = _Espia()

    resultado = _ejecutar(llamada, espia, confirmado)

    assert isinstance(resultado, HTTPException) and resultado.status_code in {400, 401}
    nombres = espia.nombres()
    assert nombres.index("record") < nombres.index("verify"), nombres
    assert nombres.count("record") == 1, "el fallo se apunta una sola vez"
    # Control previo (tope) y control tras apuntar (tope + 1: deja pasar los mismos).
    assert [e[1] for e in espia.eventos if e[0] == "lock"] == [_MAX, _MAX + 1]


@pytest.mark.parametrize("ruta", sorted(_RUTAS))
def test_en_paralelo_quien_ve_el_tope_tras_apuntar_no_verifica(ruta: str) -> None:
    llamada, confirmado = _RUTAS[ruta]
    espia = _Espia(bloqueos=[False, True])

    resultado = _ejecutar(llamada, espia, confirmado)

    assert isinstance(resultado, HTTPException) and resultado.status_code == 429
    assert "verify" not in espia.nombres()
