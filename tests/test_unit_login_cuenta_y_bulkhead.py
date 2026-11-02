"""Login, recuperación y streams: lo que no se podía forzar sin una IP por intento.

Cubre, sin BD ni argon2 real (todo simulado):

* el contador de fallos **por cuenta** del login (pausa creciente, sin bloqueo);
* que el intento se apunta **antes** de verificar la contraseña (la carrera del
  lockout: N logins en paralelo pasaban el control antes de apuntarse ninguno);
* que un correo sin cuenta ya no escribe en la auditoría (lock global);
* la agrupación de una IPv6 por su /64 en el lockout;
* el bulkhead de tres hilos del KDF (``run_kdf``) y su 503 al saturarse;
* el tope de streams SSE por cuenta y global;
* que ``ALLOW_SELF_REGISTRATION`` impide arrancar en prod/staging y que el alta
  abierta ya no acepta las invitaciones de la dirección.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request

from api.app import app
from api.routes import auth, stream
from shared.concurrency import KDF_TOKENS, kdf_limiter, reset_limiters

_CORREO = "ana@example.com"
_CONTRASENA = "no-es-la-buena-1234"  # pragma: allowlist secret


@pytest.fixture(autouse=True)
def _limiters_nuevos() -> Any:
    """El bulkhead es un singleton de proceso, atado al event loop que lo usó."""
    reset_limiters()
    yield
    reset_limiters()


def _peticion(ip: str = "203.0.113.7") -> Request:
    return Request({"type": "http", "headers": [], "client": (ip, 4321)})


# ── Pausa por cuenta ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("fallos", "desde_el_ultimo", "esperada"),
    [
        (0, 3600.0, 0.0),
        (19, 0.0, 0.0),  # bajo el umbral: nada
        (20, 0.0, 15.0),  # en el umbral: 15 s entre intentos
        (20, 15.0, 0.0),  # ya pasó la pausa
        (21, 0.0, 30.0),  # se duplica con cada fallo…
        (22, 10.0, 50.0),
        (23, 0.0, 120.0),  # …hasta dos minutos
        (500, 0.0, 120.0),  # sin desbordar con miles de fallos
        (10_000, 200.0, 0.0),
    ],
)
def test_la_pausa_por_cuenta_crece_y_tiene_techo(
    fallos: int, desde_el_ultimo: float, esperada: float
) -> None:
    assert auth._pausa_por_cuenta(fallos, desde_el_ultimo) == pytest.approx(esperada)


def test_la_clave_de_cuenta_solo_depende_del_correo() -> None:
    clave = auth._login_account_key(_CORREO)

    assert clave == auth._login_account_key("  ANA@Example.com ")
    assert clave != auth._login_account_key("otra@example.com")
    assert "ana" not in clave, "las claves acaban en rate_limits: ahí no va la dirección"


def test_el_lockout_agrupa_una_ipv6_por_su_64() -> None:
    mismo_64 = (
        auth._login_client_key(_peticion("2001:db8:1:2::1"), _CORREO),
        auth._login_client_key(_peticion("2001:db8:1:2:abcd:ef01:2345:6789"), _CORREO),
    )
    assert mismo_64[0] == mismo_64[1], "cambiar de dirección dentro del prefijo evitaba el lockout"
    assert auth._login_client_key(_peticion("2001:db8:1:3::1"), _CORREO) != mismo_64[0]
    assert auth._login_client_key(_peticion("203.0.113.7"), _CORREO) != auth._login_client_key(
        _peticion("203.0.113.8"), _CORREO
    )


# ── El handler de login ──────────────────────────────────────────────────────


class _Contadores:
    """Espía de ``db.rate_limits``: apunta el orden de todo lo que toca el login."""

    def __init__(
        self,
        *,
        bloqueos: list[tuple[bool, float]] | None = None,
        cuenta: tuple[int, float] = (0, 3600.0),
    ) -> None:
        self.eventos: list[tuple[Any, ...]] = []
        self._bloqueos = list(bloqueos or [])
        self._cuenta = cuenta

    def is_locked(self, key: str, max_attempts: int = 5, **kw: Any) -> tuple[bool, float]:
        self.eventos.append(("lock", key, max_attempts))
        return self._bloqueos.pop(0) if self._bloqueos else (False, 0.0)

    def record(self, key: str, **kw: Any) -> int:
        self.eventos.append(("record", key, kw.get("bucket", "login_fail")))
        return 1

    def clear(self, key: str, **kw: Any) -> None:
        self.eventos.append(("clear", key, kw.get("bucket", "login_fail")))

    def fallos(self, key: str, *, bucket: str, window_seconds: float) -> tuple[int, float]:
        self.eventos.append(("fallos", key, bucket))
        return self._cuenta

    def nombres(self) -> list[str]:
        return [e[0] for e in self.eventos]


def _login(
    contadores: _Contadores,
    usuario: dict[str, Any] | None,
    *,
    verifica: bool = False,
    denegado: str | None = None,
    ip: str = "203.0.113.7",
) -> tuple[Any, MagicMock]:
    """Ejecuta ``login``; devuelve el resultado o la excepción, y el espía de auditoría."""

    def _verifica(candidata: str, pw_hash: str) -> bool:
        contadores.eventos.append(("verify",))
        return verifica

    def _ficticia(candidata: str) -> bool:
        contadores.eventos.append(("dummy",))
        return False

    log_event = MagicMock()
    with (
        patch.object(auth, "get_user_by_email", return_value=usuario),
        patch.object(auth, "log_event", log_event),
        patch.object(auth, "verify_password", _verifica),
        patch.object(auth, "verify_password_against_dummy", _ficticia),
        patch.object(auth, "_motivo_login_denegado", return_value=denegado),
        patch.object(auth, "_set_session_cookie"),
        patch.object(auth, "log_access"),
        patch.object(auth, "is_admin", return_value=False),
        patch("db.totp.is_totp_required", return_value=False),
        patch("db.rate_limits.is_login_locked_out", contadores.is_locked),
        patch("db.rate_limits.record_failed_login", contadores.record),
        patch("db.rate_limits.clear_login_attempts", contadores.clear),
        patch("db.rate_limits.fallos_recientes", contadores.fallos),
    ):

        async def main() -> Any:
            try:
                resultado: Any = await auth.login(
                    auth.LoginRequest(email=_CORREO, password=_CONTRASENA),
                    Response(),
                    _peticion(ip),
                )
            except HTTPException as exc:
                resultado = exc
            # La auditoría del fallo sale con la respuesta ya enviada.
            log_event.llamadas_al_responder = log_event.call_count
            if auth._auditorias_en_vuelo:
                await asyncio.gather(*auth._auditorias_en_vuelo)
            return resultado

        resultado = asyncio.run(main())
    return resultado, log_event


_USUARIO = {"id": 7, "email": _CORREO, "password_hash": "$argon2id$v=19$m=65536,t=3,p=4$x$y"}


def test_el_intento_se_apunta_antes_de_verificar_la_contrasena() -> None:
    contadores = _Contadores()

    resultado, _ = _login(contadores, _USUARIO, verifica=False)

    assert resultado.status_code == 401
    nombres = contadores.nombres()
    assert nombres.index("record") < nombres.index("verify"), nombres
    # Control previo (tope 5) y control tras apuntar (tope 5 + 1: deja pasar los mismos cinco).
    controles = [e[2] for e in contadores.eventos if e[0] == "lock"]
    assert controles == [5, 6]


def test_en_paralelo_la_peticion_que_ve_el_tope_tras_apuntar_no_llega_a_argon2() -> None:
    contadores = _Contadores(bloqueos=[(False, 0.0), (True, 41.2)])

    resultado, _ = _login(contadores, _USUARIO, verifica=True)

    assert resultado.status_code == 429
    assert resultado.headers["Retry-After"] == "42"
    assert "verify" not in contadores.nombres(), "una contraseña correcta tampoco entra bloqueada"


def test_una_cuenta_con_muchos_fallos_exige_pausa_y_no_gasta_argon2() -> None:
    contadores = _Contadores(cuenta=(25, 10.0))

    resultado, _ = _login(contadores, _USUARIO, verifica=True)

    assert resultado.status_code == 429
    assert resultado.headers["Retry-After"] == "110"
    assert {"record", "verify", "dummy"}.isdisjoint(contadores.nombres())


def test_bajo_el_umbral_la_cuenta_no_tiene_pausa() -> None:
    resultado, _ = _login(_Contadores(cuenta=(19, 0.5)), _USUARIO, verifica=False)

    assert resultado.status_code == 401


def test_un_correo_sin_cuenta_cuenta_como_fallo_de_cuenta_y_no_audita() -> None:
    contadores = _Contadores()

    resultado, log_event = _login(contadores, None)

    assert resultado.status_code == 401
    assert resultado.detail == "Invalid credentials"
    assert "dummy" in contadores.nombres(), "sigue gastando el KDF para no delatar el correo"
    log_event.assert_not_called()  # la auditoría serializa tras un lock global
    cuenta_key = auth._login_account_key(_CORREO)
    assert ("record", cuenta_key, auth._LOGIN_CUENTA_BUCKET) in contadores.eventos


def test_una_contrasena_mala_de_una_cuenta_real_si_se_audita() -> None:
    contadores = _Contadores()

    resultado, log_event = _login(contadores, _USUARIO, verifica=False)

    assert resultado.status_code == 401
    log_event.assert_called_once()
    assert log_event.call_args.kwargs["user_id"] == 7
    assert log_event.call_args.kwargs["detail"] == {"reason": "bad_password"}
    cuenta_key = auth._login_account_key(_CORREO)
    assert ("record", cuenta_key, auth._LOGIN_CUENTA_BUCKET) in contadores.eventos


def test_la_auditoria_de_una_contrasena_mala_no_retrasa_la_respuesta() -> None:
    """Si el fallo de una cuenta que existe auditara en línea, tardaría más que el de
    una que no existe (que no audita), y el tiempo delataría qué correos tienen cuenta."""
    _, log_event = _login(_Contadores(), _USUARIO, verifica=False)

    assert log_event.llamadas_al_responder == 0, "la respuesta esperó a la auditoría"
    assert log_event.call_count == 1


def test_un_acceso_correcto_borra_el_contador_de_ip_y_el_de_cuenta() -> None:
    contadores = _Contadores()

    resultado, _ = _login(contadores, _USUARIO, verifica=True)

    assert resultado.user_id == 7
    cuenta_key = auth._login_account_key(_CORREO)
    assert ("clear", cuenta_key, auth._LOGIN_CUENTA_BUCKET) in contadores.eventos
    assert [e for e in contadores.eventos if e[0] == "clear" and e[2] == "login_fail"]


def test_una_contrasena_buena_sin_acceso_tampoco_deja_fallos() -> None:
    """La contraseña era la correcta (``email_not_verified``): no es fuerza bruta."""
    contadores = _Contadores()

    resultado, _ = _login(contadores, _USUARIO, verifica=True, denegado="email_not_verified")

    assert resultado.status_code == 403
    cuenta_key = auth._login_account_key(_CORREO)
    assert ("clear", cuenta_key, auth._LOGIN_CUENTA_BUCKET) in contadores.eventos
    assert [e for e in contadores.eventos if e[0] == "clear" and e[2] == "login_fail"]


@pytest.mark.parametrize("modelo", [auth.LoginRequest, auth.RegisterRequest])
def test_las_contrasenas_de_login_y_alta_tienen_tope(modelo: Any) -> None:
    modelo(email=_CORREO, password="a" * 512)
    with pytest.raises(ValidationError):
        modelo(email=_CORREO, password="a" * 513)


def test_el_login_corre_tras_el_bulkhead_del_kdf() -> None:
    """Si alguien vuelve a ``run_db``, los 24 hilos del pool general vuelven a poder
    ejecutar argon2 a la vez (64 MiB cada uno)."""
    import inspect

    fuente = inspect.getsource(auth.login)
    assert "run_kdf(_authenticate)" in fuente
    assert "run_db(_authenticate)" not in fuente
    assert "run_kdf(_consume)" in inspect.getsource(auth.confirm_password_reset)


# ── run_kdf ──────────────────────────────────────────────────────────────────


def test_run_kdf_ejecuta_la_funcion_una_vez_y_devuelve_el_hueco() -> None:
    from api.concurrency import run_kdf

    llamadas: list[int] = []

    async def main() -> int:
        valor = await run_kdf(lambda x: llamadas.append(x) or x * 2, 21)
        assert kdf_limiter().borrowed_tokens == 0, "el hueco se devuelve al terminar"
        return valor

    assert asyncio.run(main()) == 42
    assert llamadas == [21]


def test_run_kdf_devuelve_el_hueco_aunque_la_funcion_falle() -> None:
    from api.concurrency import run_kdf

    def _falla() -> None:
        raise ValueError("argon2 roto")

    async def main() -> None:
        with pytest.raises(ValueError, match="argon2 roto"):
            await run_kdf(_falla)
        assert kdf_limiter().borrowed_tokens == 0

    asyncio.run(main())


def test_run_kdf_no_pasa_del_cupo_de_hilos() -> None:
    from api.concurrency import run_kdf

    activos = 0
    maximo = 0
    cerrojo = threading.Lock()

    def _kdf() -> None:
        nonlocal activos, maximo
        with cerrojo:
            activos += 1
            maximo = max(maximo, activos)
        time.sleep(0.05)
        with cerrojo:
            activos -= 1

    async def main() -> None:
        await asyncio.gather(*(run_kdf(_kdf) for _ in range(12)))

    asyncio.run(main())

    assert 2 <= maximo <= KDF_TOKENS, maximo


def test_run_kdf_saturado_responde_503_con_retry_after_sin_ejecutar_nada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import api.concurrency as concurrencia

    monkeypatch.setattr(concurrencia, "_KDF_ESPERA_S", 0.05)
    llamadas: list[int] = []

    async def main() -> HTTPException:
        limiter = kdf_limiter()
        for i in range(KDF_TOKENS):  # los tres huecos, ocupados
            await limiter.acquire_on_behalf_of(f"ocupante-{i}")
        with pytest.raises(HTTPException) as exc:
            await concurrencia.run_kdf(lambda: llamadas.append(1))
        return exc.value

    rechazo = asyncio.run(main())

    assert rechazo.status_code == 503
    assert rechazo.headers is not None and rechazo.headers["Retry-After"] == "5"
    assert llamadas == []


# ── Streams SSE ──────────────────────────────────────────────────────────────


@pytest.fixture()
def sin_cupos(monkeypatch: pytest.MonkeyPatch) -> Any:
    stream._cupos.clear()
    yield
    stream._cupos.clear()


async def _abrir_stream(usuario: int) -> Any:
    async def _rapido(request: Any, last_event_id: float, batch: int) -> Any:
        yield "event: close\ndata: {}\n\n"

    # El parche solo tiene que durar lo que tarda el handler en armar la respuesta.
    with patch.object(stream, "_event_generator", _rapido):
        return await stream.licitaciones_stream(
            Request({"type": "http", "headers": [], "query_string": b""}),
            ctx={"user_id": usuario},
        )


def test_el_tercer_stream_de_una_cuenta_da_429_y_cerrar_uno_libera_el_hueco(
    sin_cupos: Any,
) -> None:
    async def main() -> None:
        primero = await _abrir_stream(1)
        await _abrir_stream(1)
        with pytest.raises(HTTPException) as exc:
            await _abrir_stream(1)
        assert exc.value.status_code == 429
        assert exc.value.headers is not None and "Retry-After" in exc.value.headers
        await _abrir_stream(2)  # otra cuenta no se ve afectada

        async for _ in primero.body_iterator:  # el stream termina…
            pass
        await _abrir_stream(1)  # …y su hueco vuelve a estar libre

    asyncio.run(main())


def test_hay_un_tope_global_de_streams(sin_cupos: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stream, "_MAX_STREAMS_GLOBAL", 3)

    async def main() -> None:
        for usuario in (1, 2, 3):
            await _abrir_stream(usuario)
        with pytest.raises(HTTPException) as exc:
            await _abrir_stream(4)
        assert exc.value.status_code == 429

    asyncio.run(main())


def test_el_hueco_se_devuelve_si_el_cliente_se_va_a_mitad(sin_cupos: Any) -> None:
    async def main() -> None:
        respuesta = await _abrir_stream(1)
        assert len(stream._cupos) == 1
        await respuesta.body_iterator.__anext__()
        await respuesta.body_iterator.aclose()  # desconexión: Starlette cierra el generador
        assert stream._cupos == []

    asyncio.run(main())


def test_un_hueco_que_nunca_arranco_caduca_solo(sin_cupos: Any) -> None:
    """Si el generador no llega a iniciarse su ``finally`` no corre: el cupo vence."""
    stream._cupos.append(("1", time.monotonic() - 1))
    stream._cupos.append(("1", time.monotonic() - 1))

    assert stream._tomar_cupo("1") is not None
    assert len(stream._cupos) == 1


# ── ALLOW_SELF_REGISTRATION ──────────────────────────────────────────────────


@pytest.mark.parametrize("env", ["prod", "staging"])
def test_el_alta_abierta_impide_arrancar_en_prod_y_staging(env: str) -> None:
    from tests.test_unit_security_review_config import _prod_settings

    with pytest.raises(Exception, match="ALLOW_SELF_REGISTRATION"):
        _prod_settings(ENV=env, ALLOW_SELF_REGISTRATION=True)


def test_el_alta_abierta_sigue_valiendo_en_dev_y_apagada_en_prod() -> None:
    from tests.test_unit_security_review_config import _prod_settings

    assert _prod_settings(ENV="dev", ALLOW_SELF_REGISTRATION=True).ALLOW_SELF_REGISTRATION
    assert not _prod_settings(ENV="prod").ALLOW_SELF_REGISTRATION


def test_el_alta_abierta_no_acepta_las_invitaciones_de_la_direccion() -> None:
    """Sin probar el buzón, quien registra primero la dirección heredaba sus invitaciones."""
    with (
        patch.object(auth.settings, "ALLOW_SELF_REGISTRATION", True),
        patch("api.routes.auth.get_user_by_email", return_value=None),
        patch("api.routes.auth.create_user", return_value=7),
        patch("api.routes.auth._activar_invitaciones") as activar,
        patch("api.routes.auth._set_session_cookie"),
        patch("api.routes.auth.log_access"),
    ):
        respuesta = TestClient(app).post(
            "/api/v1/auth/register",
            json={
                "email": "alta@example.com",
                "password": "AltaAbierta2026Segura",  # pragma: allowlist secret # gitleaks:allow
            },
        )

    assert respuesta.status_code == 201, respuesta.text
    activar.assert_not_called()
