"""El guard de red de ``tests/conftest.py``: un test ``unit`` no sale de la máquina.

Lo que se fija aquí es que salir **falla**, no que se simule «sin red». La
diferencia importa: ``shared/release_assets.py`` se traga cualquier
``Exception``, así que un stub que lanzara ``OSError`` dejaría pasar en verde al
test que descarga un modelo de GitHub sin querer — que es exactamente el caso
que motivó el guard (2026-09-27, PR #366).
"""

from __future__ import annotations

import contextlib
import re
import socket
from collections.abc import Iterator

import pytest

# Capturado al importar el módulo, antes de que ningún fixture parchee nada.
_GETADDRINFO_REAL = socket.getaddrinfo

Corte = pytest.fail.Exception

# TEST-NET-3 (RFC 5737): reservada para documentación, no la enruta nadie. Si
# el guard no estuviera, el `connect` agotaría su timeout en vez de llegar a
# ningún sitio.
_IP_EXTERNA = "203.0.113.7"


@contextlib.contextmanager
def _corte_esperado(salidas: list[str], destino: str) -> Iterator[None]:
    """El bloque tiene que cortarse intentando llegar a ``destino``.

    Vacía ``salidas`` al salir: estos tests provocan el corte a propósito, y
    sin eso el guard los dejaría en rojo al terminar, que es justo lo que hace
    con un test de verdad (`test_un_corte_que_el_codigo_se_traga…`).
    """
    with pytest.raises(Corte, match=re.escape(destino)):
        yield
    assert len(salidas) == 1
    salidas.clear()


def test_resolver_un_host_externo_hace_fallar_el_test(
    _sin_red_en_tests_unitarios: list[str],
) -> None:
    with _corte_esperado(_sin_red_en_tests_unitarios, "example.com"):
        socket.getaddrinfo("example.com", 443)


def test_conectar_a_una_ip_externa_hace_fallar_el_test(
    _sin_red_en_tests_unitarios: list[str],
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        with _corte_esperado(_sin_red_en_tests_unitarios, _IP_EXTERNA):
            sock.connect((_IP_EXTERNA, 443))


def test_connect_ex_a_una_ip_externa_hace_fallar_el_test(
    _sin_red_en_tests_unitarios: list[str],
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        with _corte_esperado(_sin_red_en_tests_unitarios, _IP_EXTERNA):
            sock.connect_ex((_IP_EXTERNA, 443))


def test_un_except_exception_no_se_traga_el_corte(
    _sin_red_en_tests_unitarios: list[str],
) -> None:
    """El corte atraviesa el ``except Exception`` del código bajo prueba."""

    def descarga_que_se_traga_los_errores() -> str:
        try:
            socket.getaddrinfo("objects.githubusercontent.com", 443)
        except Exception:
            return "sin modelo"
        return "modelo descargado"

    with _corte_esperado(_sin_red_en_tests_unitarios, "objects.githubusercontent.com"):
        descarga_que_se_traga_los_errores()


def test_el_loopback_sigue_abierto() -> None:
    """Un servidor de pega en la propia máquina no es «la red»."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as servidor:
        servidor.bind(("127.0.0.1", 0))
        servidor.listen(1)
        with socket.create_connection(servidor.getsockname(), timeout=2) as cliente:
            assert cliente.getpeername() == servidor.getsockname()


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1", "192.168.1.1", None])
def test_resolver_sin_salir_de_la_maquina_no_se_corta(host: str | None) -> None:
    """Loopback y literales de IP: ``getaddrinfo`` no consulta a ningún DNS.

    El literal privado entra a propósito: ``shared/ssrf.py`` pasa por
    ``getaddrinfo`` también las IP, y cortarlo rompería sus tests sin que nada
    hubiera salido a la red.
    """
    assert socket.getaddrinfo(host, 80, type=socket.SOCK_STREAM)


@pytest.mark.xfail(
    strict=True, raises=Corte, reason="un corte tragado tiene que dejar el test en rojo"
)
def test_un_corte_que_el_codigo_se_traga_deja_el_test_en_rojo() -> None:
    """``except BaseException``, un hilo, un ``gather(return_exceptions=True)``…

    Ahí el corte no llega al test. Lo que llega es un fallo al terminar: el
    cuerpo de abajo acaba sin error y el test **no** pasa. Por eso va con
    ``xfail(strict=True)``: si el mecanismo dejara de funcionar, el test
    pasaría, y un XPASS estricto es un fallo.
    """
    with contextlib.suppress(BaseException):
        socket.getaddrinfo("example.com", 443)


def test_integration_no_lleva_el_guard() -> None:
    """Solo se vigila a los ``unit``; este, por su nombre, queda ``integration``."""
    assert socket.getaddrinfo is _GETADDRINFO_REAL
