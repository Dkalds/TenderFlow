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

Al final van dos cosas que sí pasan por el servicio, con el servicio sustituido
por uno que responde lo justo: la traducción a 403 de los dos rechazos de la
organización y el filtro ``organo`` de ``GET /cuentas``. Tampoco abren base.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from types import FunctionType
from typing import Any, NoReturn, Protocol
from urllib.parse import parse_qsl

import pytest
from fastapi.testclient import TestClient

from api.routes.dual_auth import require_any_auth
from services.organizations import OrganizationAccessError, OrganizationPermissionError

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
        "post", _CUENTAS, {"organo": "Ayuntamiento de Soria"}, "crear_cuenta", id="POST-cuentas"
    ),
    pytest.param(
        "post",
        _CUENTAS,
        {"nombre": "Ayuntamiento de Madrid", "organos": ["Área de Gobierno de Economía"]},
        "crear_cuenta",
        id="POST-cuenta-varios-organos",
    ),
    pytest.param("get", f"{_CUENTAS}/resumen", None, "resumen_cuentas", id="GET-resumen"),
    pytest.param(
        "get", f"{_CUENTAS}/buscar-organos?q=madrid", None, "buscar_organos", id="GET-buscar"
    ),
    pytest.param("get", f"{_CUENTAS}/7", None, "ficha_cuenta", id="GET-ficha"),
    pytest.param("patch", f"{_CUENTAS}/7", {"nota": "Renueva"}, "editar_cuenta", id="PATCH-cuenta"),
    pytest.param(
        "post", f"{_CUENTAS}/7/organos", {"organos": ["Pleno"]}, "anadir_organos", id="POST-organos"
    ),
    pytest.param("delete", f"{_CUENTAS}/7/organos/3", None, "quitar_organo", id="DELETE-organo"),
    pytest.param(
        "delete",
        f"{_CUENTAS}/por-organo?organo=Pleno",
        None,
        "dejar_de_seguir_organo",
        id="DELETE-por-organo",
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
    """La query escrita en la ruta (``?q=madrid``) se suma a ``params``.

    Pasarla tal cual no basta: ``httpx`` sustituye la query de la URL por la
    de ``params`` en vez de sumarlas, y la ruta llegaría sin su ``q``.
    """
    camino, _, consulta = ruta.partition("?")
    query: dict[str, Any] = dict(parse_qsl(consulta))
    query.update(params)
    return http.request(metodo.upper(), camino, params=query, json=cuerpo)


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
        ("get", _CUENTAS, {"organo": ""}),
        ("get", _CUENTAS, {"organo": "x" * 501}),
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


# ── 403: los dos rechazos de la organización ────────────────────────────────


@pytest.mark.parametrize(
    "rechazo",
    [OrganizationAccessError, OrganizationPermissionError],
    ids=["sin-membresia", "viewer"],
)
@pytest.mark.parametrize(("metodo", "ruta", "cuerpo", "servicio"), _PETICIONES_VALIDAS)
def test_un_rechazo_de_la_organizacion_es_403_con_su_motivo(
    autenticado: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    metodo: str,
    ruta: str,
    cuerpo: dict[str, Any] | None,
    servicio: str,
    rechazo: type[PermissionError],
) -> None:
    """Las nueve rutas traducen los dos rechazos de ``resolve_organization``.

    Son hermanos, no padre e hijo, y las rutas sólo capturaban el de «no eres
    miembro»: el del viewer que escribe salía como 500. Desde que el botón
    «Seguir» del panel de órgano de Mercado escribe en /cuentas, ese viewer es
    cualquiera que lo pulse. Con ``raise_server_exceptions=True`` una excepción
    sin traducir revienta aquí con su nombre, no como un código que interpretar.
    """
    import api.routes.cuentas as rutas

    def _rechaza(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise rechazo("El rol viewer es de solo lectura.")

    monkeypatch.setattr(rutas, servicio, _rechaza)

    resp = _pedir(autenticado, metodo, ruta, cuerpo, organization_id=1)

    assert resp.status_code == 403, f"{servicio}: {resp.status_code} {resp.text}"
    # El aviso del frontend enseña `detail`: tiene que decir por qué.
    assert resp.json()["detail"] == "El rol viewer es de solo lectura."


# ── GET /cuentas?organo= ─────────────────────────────────────────────────────


def test_el_filtro_por_organo_llega_entero_al_servicio(
    autenticado: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La pregunta del botón «Seguir» de Mercado viaja tal cual hasta el servicio.

    Tal cual, sin plegar: el plegado es de ``db/`` (``clave_de_organo``), y si
    la ruta lo hiciera por su cuenta habría dos sitios que tienen que coincidir.
    Sin ``organo`` llega ``None``, que es la cartera entera de /cuentas. Que el
    plegado case contra la base lo fija ``test_cuentas_objetivo_etiquetas.py``.
    """
    import api.routes.cuentas as rutas

    llamadas: list[dict[str, Any]] = []

    def _listar(user_id: int, **kwargs: Any) -> list[Any]:
        llamadas.append({"user_id": user_id, **kwargs})
        return []

    monkeypatch.setattr(rutas, "listar_cuentas", _listar)

    con_organo = autenticado.get(
        _CUENTAS, params={"organization_id": 1, "organo": " AYUNTAMIENTO DE SORIA"}
    )
    sin_organo = autenticado.get(_CUENTAS, params={"organization_id": 1})

    assert con_organo.status_code == sin_organo.status_code == 200
    assert con_organo.json() == []
    assert llamadas == [
        {"user_id": 5, "organization_id": 1, "organo": " AYUNTAMIENTO DE SORIA"},
        {"user_id": 5, "organization_id": 1, "organo": None},
    ]


# ── Cuentas de varios órganos (v142): cuerpos y parámetros ──────────────────

_NUL = "EXP" + chr(0) + "1"


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"organo": "Ayuntamiento de Soria", "organos": ["Pleno del Ayuntamiento de Soria"]},
        {"organos": []},
        {"organos": ["x" * 501]},
        {"organos": [f"Órgano {n}" for n in range(51)]},
        {"organos": ["   "]},
        {"organos": [_NUL]},
        {"nombre": "   ", "organos": ["Pleno del Ayuntamiento de Soria"]},
        {"nombre": _NUL, "organos": ["Pleno del Ayuntamiento de Soria"]},
        {"nombre": "Cliente sin órganos"},
    ],
    ids=[
        "organo-y-organos",
        "lista-vacia",
        "organo-largo",
        "mas-de-50",
        "organo-en-blanco",
        "organo-nul",
        "nombre-en-blanco",
        "nombre-nul",
        "nombre-sin-organos",
    ],
)
def test_crear_una_cuenta_con_un_cuerpo_invalido_es_422(
    autenticado: TestClient, cuerpo: dict[str, Any]
) -> None:
    """Uno de los dos caminos, nunca los dos ni ninguno: con los dos a la vez no
    habría forma de saber si el cliente pedía seguir un órgano o crear un
    cliente con varios."""
    resp = autenticado.post(_CUENTAS, params={"organization_id": 1}, json=cuerpo)

    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize(
    "cuerpo",
    [
        {},
        {"nombre": None},
        {"nombre": "   "},
        {"nombre": "x" * 501},
        {"nota": "x" * 2001},
        {"nombre": _NUL},
        {"nota": _NUL},
        {"nota": "Renueva", "organization_id": 1},
    ],
    ids=[
        "vacio",
        "nombre-nulo",
        "nombre-en-blanco",
        "nombre-largo",
        "nota-larga",
        "nombre-nul",
        "nota-nul",
        "campo-extra",
    ],
)
def test_editar_una_cuenta_con_un_cuerpo_invalido_es_422(
    autenticado: TestClient, cuerpo: dict[str, Any]
) -> None:
    """Un PATCH sin nada que cambiar no es un éxito silencioso, y una cuenta no
    puede quedarse sin nombre: ``nombre: null`` no es «bórralo»."""
    resp = autenticado.patch(f"{_CUENTAS}/7", params={"organization_id": 1}, json=cuerpo)

    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize(
    "cuerpo",
    [{}, {"organos": []}, {"organos": [_NUL]}, {"organos": ["Pleno"], "extra": 1}],
    ids=["vacio", "lista-vacia", "organo-nul", "campo-extra"],
)
def test_anadir_organos_con_un_cuerpo_invalido_es_422(
    autenticado: TestClient, cuerpo: dict[str, Any]
) -> None:
    resp = autenticado.post(f"{_CUENTAS}/7/organos", params={"organization_id": 1}, json=cuerpo)

    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize(
    ("metodo", "ruta", "params"),
    [
        ("get", f"{_CUENTAS}/buscar-organos", {}),
        ("get", f"{_CUENTAS}/buscar-organos", {"q": "x" * 201}),
        ("get", f"{_CUENTAS}/no-es-un-id", {}),
        ("patch", f"{_CUENTAS}/no-es-un-id", {}),
        ("delete", f"{_CUENTAS}/7/organos/no-es-un-id", {}),
        ("get", f"{_CUENTAS}/resumen", {"organization_id": 0}),
        ("delete", f"{_CUENTAS}/por-organo", {}),
        ("delete", f"{_CUENTAS}/por-organo", {"organo": "x" * 501}),
    ],
    ids=[
        "buscar-sin-q",
        "buscar-q-larga",
        "ficha-id-invalido",
        "patch-id-invalido",
        "organo-id-invalido",
        "resumen-organizacion-cero",
        "dejar-organo-sin-organo",
        "dejar-organo-largo",
    ],
)
def test_parametros_invalidos_de_las_rutas_nuevas_son_422(
    autenticado: TestClient, metodo: str, ruta: str, params: dict[str, Any]
) -> None:
    """El byte NUL en la *query* no está aquí: lo corta antes el middleware con
    un 400 para cualquier ruta, sin llegar a la validación."""
    cuerpo = {"nota": "Renueva"} if metodo == "patch" else None

    resp = autenticado.request(metodo.upper(), ruta, params=params, json=cuerpo)

    assert resp.status_code == 422, resp.text


# ── 409 y 404: la traducción de lo que el servicio responde ─────────────────

#: Las rutas que pueden chocar con el resto de la cartera, con su servicio.
_ESCRITURAS_CON_CONFLICTO = [
    pytest.param(
        "post",
        _CUENTAS,
        {"nombre": "Ayuntamiento de Madrid", "organos": ["Pleno"]},
        "crear_cuenta",
        id="POST-cuentas",
    ),
    pytest.param("patch", f"{_CUENTAS}/7", {"nombre": "Otro"}, "editar_cuenta", id="PATCH-cuenta"),
    pytest.param(
        "post", f"{_CUENTAS}/7/organos", {"organos": ["Pleno"]}, "anadir_organos", id="POST-organos"
    ),
    pytest.param("delete", f"{_CUENTAS}/7/organos/3", None, "quitar_organo", id="DELETE-organo"),
]


@pytest.mark.parametrize(
    "conflicto",
    ["OrganoEnOtraCuentaError", "CuentaNombreOcupadoError", "UltimoOrganoError"],
)
@pytest.mark.parametrize(("metodo", "ruta", "cuerpo", "servicio"), _ESCRITURAS_CON_CONFLICTO)
def test_un_conflicto_con_la_cartera_es_409_con_su_motivo(
    autenticado: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    metodo: str,
    ruta: str,
    cuerpo: dict[str, Any] | None,
    servicio: str,
    conflicto: str,
) -> None:
    """El mensaje del servicio nombra el conflicto («ya está en la cuenta X») y
    es lo que el aviso del frontend enseña: la ruta lo pasa tal cual."""
    import api.routes.cuentas as rutas
    import services.cuentas as svc

    error = getattr(svc, conflicto)

    def _choca(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise error("«Pleno» ya está en la cuenta «Ayuntamiento de Madrid».")

    monkeypatch.setattr(rutas, servicio, _choca)

    resp = _pedir(autenticado, metodo, ruta, cuerpo, organization_id=1)

    assert resp.status_code == 409, f"{servicio}: {resp.status_code} {resp.text}"
    assert resp.json()["detail"] == "«Pleno» ya está en la cuenta «Ayuntamiento de Madrid»."


@pytest.mark.parametrize(
    ("metodo", "ruta", "cuerpo", "servicio"),
    [
        pytest.param("get", f"{_CUENTAS}/7", None, "ficha_cuenta", id="GET-ficha"),
        pytest.param(
            "patch", f"{_CUENTAS}/7", {"nota": "Renueva"}, "editar_cuenta", id="PATCH-cuenta"
        ),
        pytest.param(
            "post",
            f"{_CUENTAS}/7/organos",
            {"organos": ["Pleno"]},
            "anadir_organos",
            id="POST-organos",
        ),
        pytest.param(
            "delete", f"{_CUENTAS}/7/organos/3", None, "quitar_organo", id="DELETE-organo"
        ),
        pytest.param(
            "delete",
            f"{_CUENTAS}/por-organo?organo=Pleno",
            None,
            "dejar_de_seguir_organo",
            id="DELETE-por-organo",
        ),
    ],
)
def test_una_cuenta_que_no_es_de_la_organizacion_es_404(
    autenticado: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    metodo: str,
    ruta: str,
    cuerpo: dict[str, Any] | None,
    servicio: str,
) -> None:
    """``None`` del servicio es «no está en tu organización», no un 200 vacío."""
    import api.routes.cuentas as rutas

    monkeypatch.setattr(rutas, servicio, lambda *_a, **_k: None)

    resp = _pedir(autenticado, metodo, ruta, cuerpo, organization_id=1)

    assert resp.status_code == 404, f"{servicio}: {resp.status_code} {resp.text}"


@pytest.mark.parametrize(
    ("cuerpo", "esperado"),
    [
        ({"nota": None}, {"nombre": None, "nota": None, "cambiar_nota": True}),
        ({"nota": "Renueva"}, {"nombre": None, "nota": "Renueva", "cambiar_nota": True}),
        ({"nombre": " Madrid "}, {"nombre": "Madrid", "nota": None, "cambiar_nota": False}),
    ],
    ids=["borra-la-nota", "cambia-la-nota", "solo-renombra"],
)
def test_editar_distingue_no_tocar_la_nota_de_borrarla(
    autenticado: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    cuerpo: dict[str, Any],
    esperado: dict[str, Any],
) -> None:
    """Las dos llegan como ``nota=None``; lo que las separa es si el campo vino.

    Renombrar sin mandar ``nota`` no puede borrar la que hubiera, que es lo que
    haría leer sólo el valor.
    """
    import api.routes.cuentas as rutas

    llamadas: list[dict[str, Any]] = []

    def _editar(_user_id: int, _cuenta_id: int, **kwargs: Any) -> None:
        llamadas.append({k: kwargs[k] for k in ("nombre", "nota", "cambiar_nota")})

    monkeypatch.setattr(rutas, "editar_cuenta", _editar)

    autenticado.patch(f"{_CUENTAS}/7", params={"organization_id": 1}, json=cuerpo)

    assert llamadas == [esperado]
