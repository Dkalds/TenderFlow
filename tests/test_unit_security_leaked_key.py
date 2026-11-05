"""``POST /security/leaked-key`` no bloquea el event loop ni martillea a GitHub.

La ruta no tiene auth previa: la firma se verifica descargando las claves de
GitHub con ``httpx.get`` síncrono, y la revocación iba a BD también en el loop.
Además, con la caché vacía tras un fallo, cada POST reintentaba la descarga.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from api.routes import security


@pytest.fixture(autouse=True)
def _cache_vacia(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "_github_keys_cache", None)


def _en_el_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def test_tras_un_fallo_no_se_reintenta_la_descarga_en_cada_peticion() -> None:
    get = MagicMock(side_effect=httpx.ConnectError("caido"))
    with patch.object(security.httpx, "get", get):
        for _ in range(3):
            with pytest.raises(Exception):  # noqa: B017 -- el error concreto da igual aquí
                security._github_public_key("k1")

    assert get.call_count == 1


def test_si_falla_el_refresco_se_siguen_usando_las_claves_anteriores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(security, "_github_keys_cache", (0.0, {"k1": "PEM"}))
    get = MagicMock(side_effect=httpx.ConnectError("caido"))
    with patch.object(security.httpx, "get", get):
        assert security._github_public_key("k1") == "PEM"
        assert security._github_public_key("k1") == "PEM"

    assert get.call_count == 1


class _Peticion:
    def __init__(self, cuerpo: bytes) -> None:
        self._cuerpo = cuerpo

    async def body(self) -> bytes:
        return self._cuerpo


def test_la_firma_y_la_revocacion_corren_fuera_del_event_loop() -> None:
    en_el_loop: dict[str, bool] = {}

    def _verifica(*_a: Any) -> None:
        en_el_loop["firma"] = _en_el_loop()

    def _revoca(key_hash: str) -> bool:
        en_el_loop["revocar"] = _en_el_loop()
        return True

    cuerpo = json.dumps([{"token": "lic_x", "type": "t", "url": "u"}]).encode()
    with (
        patch.object(security, "_verify_github_signature", _verifica),
        patch("api.auth.revoke_api_key", _revoca),
        patch("api.auth.hash_api_key", return_value="h" * 64),
        patch("db.audit.log_event"),
    ):
        resultado = asyncio.run(
            security.leaked_key_notification(_Peticion(cuerpo), "id", "firma")  # type: ignore[arg-type]  # doble de Request: solo se usa .body()
        )

    assert resultado[0]["label"] == "true_positive"
    assert en_el_loop == {"firma": False, "revocar": False}
