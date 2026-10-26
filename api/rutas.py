"""Las rutas de la app como lista plana, sin depender de cómo las guarde FastAPI.

Hasta fastapi 0.136 ``include_router`` copiaba cada ``APIRoute`` con el prefijo
aplicado y la dejaba en ``app.routes``: recorrer esa lista era recorrer la API.
Desde 0.137 los routers incluidos quedan como objetos ``_IncludedRouter``
opacos, sin ``.path`` ni ``.methods``, y la ``APIRoute`` que el router deja en
``scope["route"]`` es la original, con su ruta **sin** el prefijo del
``include_router`` (``/licitaciones/{id}`` en vez de ``/api/v1/licitaciones/{id}``).
Con ese salto ``scripts/gen_status.py`` pasaba de 154 endpoints a 7 sin fallar,
y el access log y la métrica de coste habrían perdido el prefijo (PR #187).

Este módulo es el único sitio que sabe de esa diferencia:

* :func:`rutas_planas` recorre con ``fastapi.routing.iter_route_contexts``, la
  función pública con la que el propio ``app.openapi()`` aplana los routers
  desde 0.141, y con ``.routes`` tal cual en las versiones que ya las aplanaban.
* :func:`operaciones` es la superficie como pares ``(MÉTODO, plantilla)``. El
  ancla es ``app.openapi()``: cada operación del esquema tiene que aparecer en
  el recorrido, o falla. El recorrido aporta lo que el esquema no puede decir
  —las rutas ``include_in_schema=False`` (``/``, ``/metrics``, los receptores de
  ``/security``) y el conversor de ``{id_externo:path}``, que OpenAPI borra—.
* :func:`plantilla_de_ruta` devuelve la plantilla completa de la petición en
  curso para etiquetar logs y métricas sin cardinalidad por id.
"""

from __future__ import annotations

import re
import weakref
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

import fastapi.routing
from fastapi.dependencies.models import Dependant
from starlette.routing import BaseRoute
from starlette.types import Scope

#: Métodos que cuentan como operación. ``HEAD`` y ``OPTIONS`` los añade el
#: framework a cada ``GET`` o los responde el middleware de CORS: no son
#: superficie que alguien haya decidido exponer.
METODOS_OPERACION = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})

_CONVERSOR = re.compile(r"\{(\w+):[^}]+\}")


@dataclass(frozen=True)
class RutaPlana:
    """Una ruta ya resuelta: plantilla con todos los prefijos y sus métodos.

    ``original`` es el objeto que el router deja en ``scope["route"]`` al casar
    la petición; ``dependant`` y ``endpoint`` son los efectivos (con las
    dependencias que añada el ``include_router``), que es lo que importa a quien
    inspecciona la cadena de autenticación.
    """

    plantilla: str
    metodos: frozenset[str]
    original: BaseRoute
    endpoint: Callable[..., object] | None
    dependant: Dependant | None


def _contextos(rutas: Sequence[BaseRoute]) -> list[object]:
    # `iter_route_contexts` existe desde fastapi 0.141; antes `.routes` ya venía
    # aplanado y cada ruta es su propio contexto. Se lee con getattr porque su
    # tipo (`RouteContext`) no existe en las versiones viejas.
    iterar = getattr(fastapi.routing, "iter_route_contexts", None)
    if callable(iterar):
        return list(cast("Iterable[object]", iterar(rutas)))
    return list(rutas)


def rutas_planas(rutas: Sequence[BaseRoute]) -> list[RutaPlana]:
    """Rutas con plantilla y métodos, en orden de registro (el de enrutado).

    Acepta ``app.routes`` o el ``.routes`` de un ``APIRouter`` suelto. Omite
    lo que no tiene plantilla o métodos (un ``Mount``, un websocket).
    """
    planas: list[RutaPlana] = []
    for contexto in _contextos(rutas):
        plantilla = getattr(contexto, "path", None)
        metodos = getattr(contexto, "methods", None)
        if not isinstance(plantilla, str) or not plantilla or not metodos:
            continue
        original = getattr(contexto, "original_route", contexto)
        if not isinstance(original, BaseRoute):
            continue
        planas.append(
            RutaPlana(
                plantilla=plantilla,
                metodos=frozenset(str(m) for m in metodos),
                original=original,
                endpoint=getattr(contexto, "endpoint", None),
                dependant=getattr(contexto, "dependant", None),
            )
        )
    return planas


def plantilla_openapi(plantilla: str) -> str:
    """``/x/{id:path}`` → ``/x/{id}``: la forma con la que OpenAPI publica la ruta."""
    return _CONVERSOR.sub(r"{\1}", plantilla)


def operaciones_del_esquema(esquema: Mapping[str, object]) -> set[tuple[str, str]]:
    """Pares ``(MÉTODO, ruta)`` que publica un documento OpenAPI."""
    rutas = esquema.get("paths")
    if not isinstance(rutas, Mapping):
        return set()
    return {
        (str(metodo).upper(), str(ruta))
        for ruta, item in rutas.items()
        if isinstance(item, Mapping)
        for metodo in item
        if str(metodo).upper() in METODOS_OPERACION
    }


class IntrospeccionRotaError(RuntimeError):
    """El recorrido de rutas no ve operaciones que el esquema OpenAPI sí publica."""


def operaciones(app: fastapi.FastAPI) -> list[tuple[str, str]]:
    """Superficie de la app como ``(MÉTODO, plantilla)``, ordenada por ruta.

    La plantilla conserva el conversor (``{id_externo:path}``) y la lista
    incluye las rutas fuera del esquema. Lanza :class:`IntrospeccionRotaError`
    si alguna operación de ``app.openapi()`` no aparece en el recorrido: es el
    modo de fallo de la subida a 0.141 —contar 7 operaciones en vez de 154 sin
    que nada avisara—, y aquí tiene que ser ruidoso.
    """
    pares = {
        (metodo, ruta.plantilla)
        for ruta in rutas_planas(app.routes)
        for metodo in ruta.metodos & METODOS_OPERACION
    }
    vistas = {(metodo, plantilla_openapi(plantilla)) for metodo, plantilla in pares}
    faltan = sorted(operaciones_del_esquema(app.openapi()) - vistas)
    if faltan:
        muestra = ", ".join(f"{m} {r}" for m, r in faltan[:5])
        raise IntrospeccionRotaError(
            f"{len(faltan)} operación(es) de app.openapi() no aparecen al recorrer "
            f"las rutas ({muestra}…): la forma en que FastAPI guarda los routers "
            "incluidos cambió y api/rutas.py tiene que seguirla."
        )
    return sorted(pares, key=lambda par: (par[1], par[0]))


# Plantilla completa por ruta original, calculada una vez por app. Clave débil:
# los tests montan muchas apps y no deben quedar vivas por esta caché.
_PLANTILLAS: weakref.WeakKeyDictionary[object, tuple[int, dict[int, str]]] = (
    weakref.WeakKeyDictionary()
)


def _plantillas(app: object) -> dict[int, str]:
    rutas = getattr(app, "routes", None)
    if not isinstance(rutas, list):
        return {}
    guardado = _PLANTILLAS.get(app)
    if guardado is not None and guardado[0] == len(rutas):
        return guardado[1]
    mapa: dict[int, str] = {}
    repetidas: set[int] = set()
    for ruta in rutas_planas(rutas):
        clave = id(ruta.original)
        if clave in mapa and mapa[clave] != ruta.plantilla:
            # Un mismo router incluido con dos prefijos: la ruta original no
            # dice cuál casó. Mejor sin plantilla que con la del otro prefijo.
            repetidas.add(clave)
        mapa[clave] = ruta.plantilla
    for clave in repetidas:
        del mapa[clave]
    try:
        _PLANTILLAS[app] = (len(rutas), mapa)
    except TypeError:
        pass  # app sin referencia débil posible: se recalcula, no se cachea
    return mapa


def plantilla_de_ruta(scope: Scope) -> str | None:
    """Plantilla completa (``/api/v1/licitaciones/{id_externo:path}``) de la petición.

    ``None`` si ninguna ruta casó. Se lee después de que el router haya fijado
    ``scope["route"]``.
    """
    ruta = scope.get("route")
    if ruta is None:
        return None
    completa = _plantillas(scope.get("app")).get(id(ruta))
    if completa is not None:
        return completa
    propia = getattr(ruta, "path", None)
    return propia if isinstance(propia, str) else None
