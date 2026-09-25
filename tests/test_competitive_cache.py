"""Caché de los agregados globales de ``/competitive/*`` (sin BD).

Renovaciones, bajas, cuota y HHI agregan ``adjudicaciones`` enteras y se
recalculaban en cada petición. Ahora se cachean como la analítica global de
``/analytics/*``. El cableado se fija aquí de dos formas que se complementan:

- **Declaración**: qué rutas llevan ``@cache_response``, con qué TTL, sin
  ``user_scoped`` y por debajo de ``@router.get`` —en el otro orden FastAPI
  registraría la función sin caché—. Se lee del AST del módulo, así que no
  depende de cómo implemente ``shared/cache.py`` el decorador por dentro.
- **Comportamiento**: con los servicios sustituidos por contadores, dos
  usuarios comparten un único cálculo, y cambiar **cualquier** parámetro de la
  consulta da otra entrada. Si un parámetro no entrara en la clave, dos
  consultas distintas compartirían respuesta.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import anyio
import pytest
from pydantic import BaseModel

from api.routes import analytics as analytics_routes
from api.routes import competitive
from shared.cache import reset_cache
from shared.metric_scope import MetricScope

#: Ruta cacheada → path con el que se registra.
_RUTAS_CACHEADAS = {
    "get_renovaciones": "/renovaciones",
    "get_renovaciones_resumen": "/renovaciones/resumen",
    "get_bajas": "/bajas",
    "get_baja_referencia": "/bajas/referencia",
    "get_cuota": "/cuota",
    "get_hhi": "/hhi",
}


@pytest.fixture(autouse=True)
def _cache_vacia():
    """La caché de respuestas es de proceso: sin vaciarla, un test vería la de otro."""
    reset_cache("analytics")
    yield
    reset_cache("analytics")


# ---------------------------------------------------------------------------
# Declaración
# ---------------------------------------------------------------------------


def _funciones(modulo: Any) -> dict[str, ast.AsyncFunctionDef | ast.FunctionDef]:
    arbol = ast.parse(Path(modulo.__file__).read_text(encoding="utf-8"))
    return {
        nodo.name: nodo
        for nodo in arbol.body
        if isinstance(nodo, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _es_llamada_a(nodo: ast.expr, nombre: str) -> bool:
    if not isinstance(nodo, ast.Call):
        return False
    funcion = nodo.func
    return (isinstance(funcion, ast.Name) and funcion.id == nombre) or (
        isinstance(funcion, ast.Attribute) and funcion.attr == nombre
    )


def _config_de_cache(nodo: ast.AsyncFunctionDef | ast.FunctionDef) -> dict[str, Any] | None:
    for decorador in nodo.decorator_list:
        if _es_llamada_a(decorador, "cache_response"):
            assert isinstance(decorador, ast.Call)
            assert not decorador.args, "la configuración va por nombre, como en /analytics/*"
            return {kw.arg: ast.literal_eval(kw.value) for kw in decorador.keywords}
    return None


def test_los_agregados_globales_llevan_cache_compartida_bajo_el_router():
    funciones = _funciones(competitive)
    for nombre, path in _RUTAS_CACHEADAS.items():
        decoradores = funciones[nombre].decorator_list
        assert len(decoradores) == 2, nombre
        router, cache = decoradores
        # `@router.get` fuera y `@cache_response` dentro: FastAPI registra lo
        # que devuelve el decorador más externo.
        assert _es_llamada_a(router, "get"), nombre
        assert isinstance(router, ast.Call)
        assert ast.literal_eval(router.args[0]) == path
        assert _es_llamada_a(cache, "cache_response"), nombre
        # Sin `namespace`: el de la analítica global, el mismo que invalidan
        # y dimensionan los demás endpoints agregados.
        assert _config_de_cache(funciones[nombre]) == {"ttl": 300, "user_scoped": False}, nombre


def test_el_ttl_es_el_de_la_analitica_global_hermana():
    """Mismo TTL que ``/analytics/competitors``: dos vistas del mismo mercado."""
    competidores = _config_de_cache(_funciones(analytics_routes)["competitors"])
    assert competidores is not None
    assert competidores["user_scoped"] is False
    for nombre in _RUTAS_CACHEADAS:
        config = _config_de_cache(_funciones(competitive)[nombre])
        assert config is not None
        assert config["ttl"] == competidores["ttl"], nombre


def test_lo_que_depende_del_usuario_o_de_una_empresa_no_se_cachea():
    """Watchlist, batallas o socios con una clave sin identidad se mezclarían."""
    cacheadas = {
        nombre
        for nombre, nodo in _funciones(competitive).items()
        if _config_de_cache(nodo) is not None
    }
    assert cacheadas == set(_RUTAS_CACHEADAS)


# ---------------------------------------------------------------------------
# Comportamiento
# ---------------------------------------------------------------------------

_CTX_A = {"user_key": "usuario-a", "organization_id": 1, "user_id": 1}
_CTX_B = {"user_key": "usuario-b", "organization_id": 2, "user_id": 2}

#: Por ruta: parámetros de base y, para cada uno, otro valor válido.
_PARAMETROS: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "get_renovaciones": (
        {
            "months": 6,
            "empresa_id": None,
            "ccaa": None,
            "tecnologia": None,
            "min_importe": None,
            "order_by": "fecha",
            "limit": 200,
            "offset": 0,
        },
        {
            "months": 12,
            "empresa_id": 7,
            "ccaa": "Madrid",
            "tecnologia": "SAP",
            "min_importe": 1_000.0,
            "order_by": "score",
            "limit": 50,
            "offset": 10,
        },
    ),
    "get_renovaciones_resumen": (
        {"months": 12, "tecnologia": None},
        {"months": 6, "tecnologia": "SAP"},
    ),
    "get_bajas": (
        {
            "group_by": "empresa",
            "min_contratos": 3,
            "cpv": None,
            "ccaa": None,
            "fecha_desde": None,
            "fecha_hasta": None,
            "importe_min": None,
            "limit": 100,
            "solo_base_declarada": False,
        },
        {
            "group_by": "organo",
            "min_contratos": 4,
            "cpv": "72",
            "ccaa": "Madrid",
            "fecha_desde": date(2025, 1, 1),
            "fecha_hasta": date(2025, 12, 31),
            "importe_min": 1_000.0,
            "limit": 50,
            "solo_base_declarada": True,
        },
    ),
    "get_baja_referencia": (
        {"organo": None, "cpv": None, "solo_base_declarada": False},
        {"organo": "Ayuntamiento X", "cpv": "72", "solo_base_declarada": True},
    ),
    "get_cuota": (
        {"cpv": None, "ccaa": None, "desde": None, "limit": 50},
        {"cpv": "72", "ccaa": "Madrid", "desde": "2025-01-01", "limit": 10},
    ),
    "get_hhi": (
        {"segment_by": "cpv", "min_contratos": 5},
        {"segment_by": "ccaa", "min_contratos": 6},
    ),
}


def _scope(**_kwargs: Any) -> MetricScope:
    return MetricScope(
        label="Cuota",
        universe="technology_observed",
        denominator_records=0,
        denominator_amount_eur=0.0,
        filters={},
        sources=[],
        filter_versions=[],
        model_versions=[],
        computed_at="2026-09-24T00:00:00+00:00",
        caveat="-",
    )


@pytest.fixture
def servicios(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Sustituye los servicios de las rutas por dobles que anotan cada llamada."""
    llamadas: list[str] = []

    def contador(nombre: str, resultado: Callable[..., Any]) -> Callable[..., Any]:
        def _doble(*args: Any, **kwargs: Any) -> Any:
            llamadas.append(nombre)
            return resultado(*args, **kwargs)

        return _doble

    dobles: dict[str, Callable[..., Any]] = {
        "proximas_renovaciones": lambda **_k: [],
        "enriquecer_renovaciones": lambda filas: filas,
        "resumen_renovaciones": lambda **_k: [],
        "totales_renovaciones": lambda **_k: {
            "contratos_venciendo": 0,
            "importe_en_juego": 0,
            "importe_alto_riesgo": 0,
            "calientes": 0,
        },
        "bajas_agregadas": lambda **_k: (
            [
                {
                    "grupo_id": 1,
                    "grupo": "Empresa SL",
                    "contratos": 3,
                    "baja_media_pct": 12.5,
                    "baja_min_pct": 2.0,
                    "baja_max_pct": 30.25,
                    "importe_total": 150_000.0,
                    "ofertas_medias": 4.3,
                }
            ],
            "mixta",
        ),
        "baja_de_referencia": lambda **k: {
            "organo": k["organo"],
            "cpv_prefix": k["cpv_prefix"],
            "base": "mixta",
        },
        "cuota_mercado": lambda **_k: [],
        "concentracion_hhi": lambda **_k: [],
        "metric_scope": _scope,
    }
    for nombre, resultado in dobles.items():
        monkeypatch.setattr(competitive, nombre, contador(nombre, resultado))
    return llamadas


def _pedir(nombre: str, *peticiones: tuple[dict[str, Any], dict[str, Any]]) -> list[Any]:
    """Llama a la ruta decorada (caché incluida), en un solo event loop."""
    ruta = getattr(competitive, nombre)

    async def _todas() -> list[Any]:
        return [await ruta(**params, _ctx=ctx) for params, ctx in peticiones]

    return anyio.run(_todas)


def _normalizado(nombre: str, respuesta: Any) -> Any:
    """Un acierto de caché llega como ``dict``; se valida contra el modelo de la ruta."""
    modelo = inspect.signature(getattr(competitive, nombre).__wrapped__).return_annotation
    tipo = getattr(competitive, modelo) if isinstance(modelo, str) else modelo
    if isinstance(respuesta, BaseModel):
        return respuesta
    return tipo.model_validate(respuesta)


def test_la_tabla_cubre_todos_los_parametros_de_cada_ruta():
    """Un parámetro nuevo obliga a decidir aquí si entra en la clave."""
    for nombre, (base, otro) in _PARAMETROS.items():
        firma = inspect.signature(getattr(competitive, nombre).__wrapped__)
        consulta = {p for p in firma.parameters if not p.startswith("_")}
        assert set(base) == consulta == set(otro), nombre


@pytest.mark.parametrize("nombre", list(_RUTAS_CACHEADAS))
def test_dos_usuarios_comparten_un_solo_calculo(nombre: str, servicios: list[str]):
    base, _ = _PARAMETROS[nombre]
    primera = _pedir(nombre, (base, _CTX_A))[0]
    por_calculo = len(servicios)
    assert por_calculo > 0
    segunda, tercera = _pedir(nombre, (base, _CTX_B), (base, _CTX_A))
    assert len(servicios) == por_calculo, "otro usuario, mismos filtros: no debe recalcular"
    assert _normalizado(nombre, segunda) == _normalizado(nombre, primera)
    assert _normalizado(nombre, tercera) == _normalizado(nombre, primera)


@pytest.mark.parametrize("nombre", list(_RUTAS_CACHEADAS))
def test_cada_parametro_entra_en_la_clave(nombre: str, servicios: list[str]):
    base, otro = _PARAMETROS[nombre]
    _pedir(nombre, (base, _CTX_A))
    por_calculo = len(servicios)
    for parametro, valor in otro.items():
        antes = len(servicios)
        _pedir(nombre, ({**base, parametro: valor}, _CTX_B))
        assert len(servicios) == antes + por_calculo, f"{nombre}: `{parametro}` no está en la clave"
    # Y la consulta de base sigue servida desde la caché.
    antes = len(servicios)
    _pedir(nombre, (base, _CTX_B))
    assert len(servicios) == antes
