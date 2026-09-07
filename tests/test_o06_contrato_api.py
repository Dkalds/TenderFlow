"""O0.6 del plan 2026-09 v2: la superficie no promete lo que el backend no hace.

Cubre los apartados b, c, d y e. Cada test corresponde a un criterio de
aceptación literal del plan (docs/plans/2026-09-plan-arquitectura-v2.md §4).

Sin BD a propósito: el esquema OpenAPI se construye en proceso, igual que hace
``tests/test_export_openapi.py``, así que estos controles corren en el bucle
rápido y no dependen de que ``api/openapi.json`` esté regenerado.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _cargar_script(nombre: str) -> Any:
    """Carga un módulo de ``scripts/`` por ruta (no son un paquete importable)."""
    spec = importlib.util.spec_from_file_location(nombre, _REPO_ROOT / "scripts" / f"{nombre}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    """Esquema OpenAPI construido en proceso desde la app real.

    Se genera aquí en vez de leer ``api/openapi.json`` para que el test falle
    cuando el código cambia, no cuando alguien olvida regenerar el artefacto.
    """
    from api.app import app

    resultado: dict[str, Any] = app.openapi()
    return resultado


# ── d) El agujero del ratchet: _is_opaque no recorría arrays ────────────────
#
# El caso que se colaba es ``list[dict[str, Any]]``: el esquema de primer nivel
# es un array, no un objeto, así que la comprobación antigua lo daba por bueno
# mientras openapi-typescript emitía ``unknown[]``.

_CASOS_OPACIDAD: list[tuple[str, dict[str, Any], bool]] = [
    (
        "list[dict[str, Any]] — el hueco del ratchet",
        {"type": "array", "items": {"type": "object"}},
        True,
    ),
    ("list[Modelo]", {"type": "array", "items": {"$ref": "#/components/schemas/X"}}, False),
    ("list[Any] (sin items)", {"type": "array"}, True),
    ("dict[str, Any]", {"type": "object"}, True),
    ("Modelo por referencia", {"$ref": "#/components/schemas/X"}, False),
    ("objeto con properties", {"type": "object", "properties": {"a": {"type": "string"}}}, False),
    ("list[str]", {"type": "array", "items": {"type": "string"}}, False),
    (
        "list[list[dict]] — anidado",
        {"type": "array", "items": {"type": "array", "items": {"type": "object"}}},
        True,
    ),
    (
        "list[dict] | None",
        {"anyOf": [{"type": "array", "items": {"type": "object"}}, {"type": "null"}]},
        True,
    ),
    (
        "list[Modelo] | None",
        {"anyOf": [{"type": "array", "items": {"$ref": "#/x"}}, {"type": "null"}]},
        False,
    ),
    (
        "unión con al menos una rama tipada: no se marca",
        {"anyOf": [{"type": "object"}, {"$ref": "#/x"}]},
        False,
    ),
    ("esquema vacío", {}, True),
]


@pytest.mark.parametrize(
    ("descripcion", "esquema", "esperado"),
    _CASOS_OPACIDAD,
    ids=[c[0] for c in _CASOS_OPACIDAD],
)
def test_is_opaque_recorre_arrays_y_uniones(
    descripcion: str, esquema: dict[str, Any], esperado: bool
) -> None:
    contrato = _cargar_script("check_openapi_contract")
    assert contrato._is_opaque(esquema) is esperado, descripcion


def test_ninguna_operacion_publicada_es_opaca(spec: dict[str, Any]) -> None:
    """Criterio del plan: cero operaciones que generen ``unknown[]``.

    Con la comprobación recursiva, las tres del hecho 8 (``GET /me/keys``,
    ``GET /models/{name}/versions`` y ``GET /webhooks``) entran en el radar del
    ratchet; el test exige además que sigan tipadas.
    """
    contrato = _cargar_script("check_openapi_contract")
    assert contrato.find_opaque(spec) == []


@pytest.mark.parametrize(
    ("ruta", "metodo"),
    [
        ("/api/v1/me/keys", "get"),
        ("/api/v1/models/{name}/versions", "get"),
        ("/api/v1/webhooks", "get"),
    ],
)
def test_las_tres_operaciones_del_hecho_8_devuelven_dtos(
    spec: dict[str, Any], ruta: str, metodo: str
) -> None:
    """Las tres devolvían ``list[dict[str, Any]]``; ahora son arrays de modelo.

    Se comprueba la forma exacta —array cuyos ``items`` son un ``$ref``— y no
    solo que el ratchet pase: un ``list[str]`` también pasaría el ratchet y no
    sería lo que estas rutas tienen que devolver.
    """
    esquema = spec["paths"][ruta][metodo]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    assert esquema.get("type") == "array", f"{metodo.upper()} {ruta} ya no devuelve una lista"
    assert "$ref" in esquema.get("items", {}), (
        f"{metodo.upper()} {ruta} devuelve una lista sin modelo: el cliente TS recibiría unknown[]"
    )


# ── e) Retirada anunciada (D19) ─────────────────────────────────────────────

_DEPRECADAS = [
    ("/api/v1/analytics/compare-periods", "get"),
    ("/api/v1/analytics/resumen/sankey", "get"),
    ("/api/v1/analytics/resumen/top", "get"),
    ("/api/v1/licitaciones", "get"),
]


@pytest.mark.parametrize(("ruta", "metodo"), _DEPRECADAS)
def test_las_cuatro_operaciones_estan_deprecadas(
    spec: dict[str, Any], ruta: str, metodo: str
) -> None:
    """Las tres de analítica sin consumidor, más el listado por offset.

    Ver docs/rfc/2026-09-06-rfc-retirada-endpoints-analitica.md: la marca es lo
    único que avisa a un integrador que no lee el repositorio, y la fecha de
    borrado es el 2026-12-04.
    """
    operacion = spec["paths"][ruta][metodo]
    assert operacion.get("deprecated") is True


def test_el_listado_por_cursor_no_esta_deprecado(spec: dict[str, Any]) -> None:
    """El sustituto tiene que seguir vivo: si no, la deprecación no ofrece salida."""
    assert spec["paths"]["/api/v1/licitaciones/cursor"]["get"].get("deprecated") is not True


# ── b) Las cuatro rutas que la web no podía usar ────────────────────────────


def test_licitaciones_no_exige_api_key_en_ninguna_ruta() -> None:
    """Criterio literal del plan: ``grep -c require_api_key`` = 0 en ese fichero.

    Es un ratchet de código y no de comportamiento a propósito: comprobar el
    403 real exige BD y sesión, y eso vive en los tests de integración. Aquí lo
    que se congela es que nadie vuelva a colgar de ``require_api_key`` una ruta
    de este módulo, que es como se llegó a tener el listado recomendado
    inaccesible desde el navegador.
    """
    fuente = (_REPO_ROOT / "api" / "routes" / "licitaciones.py").read_text(encoding="utf-8")
    assert "require_api_key" not in fuente


@pytest.mark.parametrize(
    ("ruta", "metodo"),
    [
        ("/api/v1/licitaciones/cursor", "get"),
        ("/api/v1/licitaciones/{id_externo}/explain", "get"),
        ("/api/v1/licitaciones/{id_externo}/tech-scores", "get"),
        ("/api/v1/licitaciones/bulk-get", "post"),
    ],
)
def test_las_cuatro_rutas_siguen_publicadas(spec: dict[str, Any], ruta: str, metodo: str) -> None:
    """Cambiar la dependencia no puede haberlas sacado del contrato."""
    assert metodo in spec["paths"][ruta]


# ── c) Activar modelos y verificar auditoría con sesión de administrador ────


def _cadena_de_dependencias(dependant: Any, vistos: set[int] | None = None) -> set[str]:
    """Nombres de todos los callables de dependencia de una ruta, transitivos."""
    vistos = vistos if vistos is not None else set()
    if id(dependant) in vistos:
        return set()
    vistos.add(id(dependant))
    nombres: set[str] = set()
    for sub in getattr(dependant, "dependencies", []):
        llamable = getattr(sub, "call", None)
        if llamable is not None:
            nombres.add(getattr(llamable, "__name__", ""))
        nombres |= _cadena_de_dependencias(sub, vistos)
    return nombres


@pytest.mark.parametrize(
    ("ruta", "metodo"),
    [
        ("/api/v1/models/{name}/activate/{version}", "POST"),
        ("/api/v1/security/audit/verify", "GET"),
    ],
)
def test_las_dos_rutas_de_admin_aceptan_sesion(ruta: str, metodo: str) -> None:
    """Exigían ``require_scope("admin")``, que solo entiende de API keys.

    ``require_admin`` acepta sesión o key y **no relaja nada** para las keys:
    ``require_any_auth`` solo marca ``is_admin`` si el dueño lo es y la key
    lleva scope ``admin`` o ``*`` (api/routes/dual_auth.py).
    """
    from api.app import app

    for route in app.routes:
        if getattr(route, "path", None) == ruta and metodo in getattr(route, "methods", set()):
            nombres = _cadena_de_dependencias(route.dependant)
            assert "require_admin" in nombres, f"{metodo} {ruta} no depende de require_admin"
            assert "require_scope" not in nombres
            return
    pytest.fail(f"No se encontró la ruta {metodo} {ruta} en la app")
