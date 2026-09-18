"""Cuentas y etiquetas: lo que las nueve rutas rechazan **antes** del servicio.

Hermano de ``test_cuentas_objetivo_etiquetas.py``, que prueba lo que pasa
cuando la petición llega a Postgres. Aquí van las dos puertas que están
delante: la autenticación (401) y la validación de cuerpo, ruta y query (422).

**No abre base.** Cada función de ``services.cuentas`` que importan las rutas
se sustituye por una que lanza ``LlegoAlServicioError`` si alguien la llama.
Así «no escribió nada» no es una suposición sobre el orden en que FastAPI
resuelve dependencias y cuerpo, sino algo que el test comprueba: si una
validación desapareciera, o la autenticación dejara de exigirse, la petición
llegaría al servicio y el test fallaría con el nombre de la función, sin
llegar a conectar con la ``DATABASE_URL`` que tenga la máquina.

``test_una_peticion_valida_llega_a_su_servicio`` es el control del guardia: con
el mismo cliente y un cuerpo válido, cada ruta tiene que tropezar con él. Sin
ese control, un guardia apuntado a nombres equivocados dejaría pasar en verde
todos los demás tests sin probar nada.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from types import FunctionType
from typing import Any, NoReturn, Protocol

import pytest
from fastapi.testclient import TestClient

from api.routes.dual_auth import require_any_auth

_CUENTAS = "/api/v1/cuentas"
_ETIQUETAS = "/api/v1/etiquetas"


class Respuesta(Protocol):
    """Lo que estos tests leen de una respuesta del ``TestClient``.

    No se anota con ``httpx.Response``: Starlette usa ``httpx2`` si está
    instalado y ``httpx`` si no, y para mypy son dos tipos distintos.
    """

    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...

    # `Any`: el cuerpo JSON es arbitrario; cada test comprueba su forma.
    def json(self) -> Any: ...


class LlegoAlServicioError(Exception):
    """Una petición que debía rechazarse antes llegó a ``services.cuentas``."""


def _guardia(nombre: str) -> Callable[..., NoReturn]:
    # `Any` en los argumentos: sustituye a funciones con firmas distintas.
    def _servicio(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise LlegoAlServicioError(nombre)

    return _servicio


@pytest.fixture
def servicios_vigilados(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Sustituye en ``api.routes.cuentas`` cada función importada del servicio.

    Se descubren por módulo de origen en vez de listarlas a mano: una ruta
    nueva que importe otra función del servicio queda vigilada sin tocar este
    fichero. ``EtiquetaLimiteError`` también viene de ahí, pero es una clase y
    las rutas la necesitan para su ``except``.
    """
    import api.routes.cuentas as rutas

    nombres = sorted(
        nombre
        for nombre, valor in vars(rutas).items()
        if isinstance(valor, FunctionType) and valor.__module__ == "services.cuentas"
    )
    for nombre in nombres:
        monkeypatch.setattr(rutas, nombre, _guardia(nombre))
    return nombres


@pytest.fixture
def anonimo(servicios_vigilados: list[str]) -> TestClient:
    """Cliente sin sesión ni API key: ``require_any_auth`` corre de verdad."""
    from api.app import app

    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def autenticado(servicios_vigilados: list[str]) -> Iterator[TestClient]:
    """Cliente con la autenticación sustituida por un usuario fijo.

    El ``user_id`` es inventado: sólo el servicio haría algo con él, y antes
    de llegar al servicio está el guardia.
    """
    from api.app import app

    app.dependency_overrides[require_any_auth] = lambda: {
        "user_id": 5,
        "auth_method": "session",
        "user_key": "cuentas-objetivo-5",
    }
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        app.dependency_overrides.pop(require_any_auth, None)


#: Una petición válida por ruta y la función del servicio que le toca.
_PETICIONES_VALIDAS = [
    pytest.param("get", _CUENTAS, None, "listar_cuentas", id="GET-cuentas"),
    pytest.param(
        "post", _CUENTAS, {"organo": "Ayuntamiento de Soria"}, "seguir_organo", id="POST-cuentas"
    ),
    pytest.param("delete", f"{_CUENTAS}/7", None, "dejar_de_seguir", id="DELETE-cuenta"),
    pytest.param("get", _ETIQUETAS, None, "listar_etiquetas", id="GET-etiquetas"),
    pytest.param("post", _ETIQUETAS, {"nombre": "Q4"}, "crear_etiqueta", id="POST-etiquetas"),
    pytest.param("delete", f"{_ETIQUETAS}/7", None, "borrar_etiqueta", id="DELETE-etiqueta"),
    pytest.param(
        "post",
        f"{_ETIQUETAS}/aplicar",
        {"etiqueta_id": 7, "objeto_tipo": "oportunidad", "objeto_id": "17"},
        "aplicar_etiqueta",
        id="POST-aplicar",
    ),
    pytest.param(
        "post",
        f"{_ETIQUETAS}/quitar",
        {"etiqueta_id": 7, "objeto_tipo": "oportunidad", "objeto_id": "17"},
        "quitar_etiqueta",
        id="POST-quitar",
    ),
    pytest.param(
        "post",
        f"{_ETIQUETAS}/por-objeto",
        {"objeto_tipo": "oportunidad", "objeto_ids": ["17"]},
        "etiquetas_de",
        id="POST-por-objeto",
    ),
]


def _pedir(
    http: TestClient, metodo: str, ruta: str, cuerpo: dict[str, Any] | None, **params: int
) -> Respuesta:
    return http.request(metodo.upper(), ruta, params=params, json=cuerpo)


@pytest.mark.parametrize(("metodo", "ruta", "cuerpo", "servicio"), _PETICIONES_VALIDAS)
def test_una_peticion_valida_llega_a_su_servicio(
    autenticado: TestClient,
    servicios_vigilados: list[str],
    metodo: str,
    ruta: str,
    cuerpo: dict[str, Any] | None,
    servicio: str,
) -> None:
    """Control del guardia: sin él, los rechazos de abajo no probarían nada."""
    assert servicio in servicios_vigilados

    with pytest.raises(LlegoAlServicioError) as llegada:
        _pedir(autenticado, metodo, ruta, cuerpo, organization_id=1)

    assert str(llegada.value) == servicio


@pytest.mark.parametrize(("metodo", "ruta", "cuerpo", "servicio"), _PETICIONES_VALIDAS)
def test_sin_autenticar_es_401_y_no_llega_al_servicio(
    anonimo: TestClient,
    metodo: str,
    ruta: str,
    cuerpo: dict[str, Any] | None,
    servicio: str,
) -> None:
    """Las nueve rutas, con la misma petición que en el control llega al servicio.

    El cuerpo es válido a propósito: si una ruta dejara de exigir autenticación,
    la petición llegaría al guardia y el fallo nombraría la función del
    servicio, en vez de un 422 que no diría por qué.
    """
    resp = _pedir(anonimo, metodo, ruta, cuerpo, organization_id=1)

    assert resp.status_code == 401, f"{servicio}: {resp.status_code} {resp.text}"


# ── 422: cuerpo, ruta y query ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"organo": ""},
        # `str_strip_whitespace` va antes que `min_length`: sólo espacios es vacío.
        {"organo": "   "},
        {"organo": "x" * 501},
        {"organo": "Ayuntamiento de Soria", "nota": "x" * 2001},
        {"organo": "Ayuntamiento de Soria", "organization_id": 1},
        {},
    ],
    ids=["vacio", "solo-espacios", "organo-largo", "nota-larga", "campo-extra", "sin-organo"],
)
def test_seguir_con_un_cuerpo_invalido_es_422(
    autenticado: TestClient, cuerpo: dict[str, Any]
) -> None:
    resp = autenticado.post(_CUENTAS, params={"organization_id": 1}, json=cuerpo)

    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize(
    ("metodo", "ruta", "params"),
    [
        ("get", _CUENTAS, {"organization_id": 0}),
        ("post", _CUENTAS, {"organization_id": -3}),
        ("delete", f"{_CUENTAS}/no-es-un-id", {}),
        ("get", _ETIQUETAS, {"organization_id": 0}),
        ("delete", f"{_ETIQUETAS}/no-es-un-id", {}),
    ],
)
def test_parametros_de_ruta_o_query_invalidos_son_422(
    autenticado: TestClient, metodo: str, ruta: str, params: dict[str, Any]
) -> None:
    cuerpo = {"organo": "Ayuntamiento de Soria"} if metodo == "post" else None

    resp = autenticado.request(metodo.upper(), ruta, params=params, json=cuerpo)

    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"nombre": ""},
        {"nombre": "   "},
        {"nombre": "x" * 41},
        {"nombre": "Q4", "color": "rojo"},
        {"nombre": "Q4", "color": "#abc"},
        {"nombre": "Q4", "color": "#gggggg"},
        {"nombre": "Q4", "organization_id": 1},
    ],
    ids=[
        "vacio",
        "solo-espacios",
        "nombre-largo",
        "color-texto",
        "color-corto",
        "color-no-hex",
        "extra",
    ],
)
def test_crear_etiqueta_invalida_es_422(autenticado: TestClient, cuerpo: dict[str, Any]) -> None:
    resp = autenticado.post(_ETIQUETAS, params={"organization_id": 1}, json=cuerpo)

    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"etiqueta_id": 0, "objeto_tipo": "oportunidad", "objeto_id": "17"},
        {"etiqueta_id": 1, "objeto_tipo": "licitacion", "objeto_id": "17"},
        {"etiqueta_id": 1, "objeto_tipo": "oportunidad", "objeto_id": ""},
        {"etiqueta_id": 1, "objeto_tipo": "oportunidad", "objeto_id": "x" * 121},
        {"etiqueta_id": 1, "objeto_tipo": "oportunidad", "objeto_id": "17", "extra": 1},
    ],
    ids=["etiqueta-cero", "tipo-desconocido", "objeto-vacio", "objeto-largo", "campo-extra"],
)
@pytest.mark.parametrize("accion", ["aplicar", "quitar"])
def test_aplicar_o_quitar_con_cuerpo_invalido_es_422(
    autenticado: TestClient, accion: str, cuerpo: dict[str, Any]
) -> None:
    resp = autenticado.post(f"{_ETIQUETAS}/{accion}", params={"organization_id": 1}, json=cuerpo)

    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"objeto_tipo": "licitacion", "objeto_ids": ["1"]},
        {"objeto_ids": ["1"]},
        {"objeto_tipo": "favorito", "objeto_ids": [str(i) for i in range(201)]},
        # `SafeStr`: el NUL llegaba a psycopg y salía como 500.
        {"objeto_tipo": "favorito", "objeto_ids": ["EXP" + chr(0) + "1"]},
    ],
    ids=["tipo-desconocido", "sin-tipo", "mas-de-200-ids", "byte-nul"],
)
def test_por_objeto_con_cuerpo_invalido_es_422(
    autenticado: TestClient, cuerpo: dict[str, Any]
) -> None:
    resp = autenticado.post(f"{_ETIQUETAS}/por-objeto", params={"organization_id": 1}, json=cuerpo)

    assert resp.status_code == 422, resp.text
