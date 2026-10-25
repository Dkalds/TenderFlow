#!/usr/bin/env python3
"""Ratchet de la convención de la API: una paginación y una forma de error.

La convención está escrita en ``docs/api-design.md`` («Convención de la API»).
Este gate la hace cumplir en lo nuevo y congela lo heredado:

**Paginación.** Una operación pagina si recibe ``offset``, ``cursor``, ``page``,
``page_size`` o ``skip`` en la query, o si su 200 es un sobre de listado
(``next_cursor``, o ``items`` + ``total`` + ``offset``;
un ``items`` + ``total`` sin ventana es una lista completa, no una página). Cumple si pagina por ``limit`` /
``offset`` (sin ``cursor`` ni ``page``) y su 200 es ``Pagina[T]`` —el
componente ``PaginatedResponse_<T>_``—. Lo demás es una salida.

**Errores.** En el esquema, toda respuesta 4xx/5xx/``default`` es
``ProblemDetail`` en ``application/problem+json`` (lo garantiza
``api.errors.documentar_errores`` salvo que una ruta declare otro modelo). En
el código, nada en ``api/`` construye una ``Response``/``JSONResponse`` con un
código de error —o con uno que no se pueda leer—: eso se salta el manejador
único de ``api/errors.py``. Los cuerpos crudos del middleware ASGI no cuentan
porque no son llamadas a ``Response``, y ya emiten ``problem+json``.

Cómo funciona
-------------
``PAGINACION_CONGELADA``, ``ERROR_ESQUEMA_CONGELADO`` y ``ERROR_CODIGO_CONGELADO``
son las salidas que existían al escribir el gate, cada una con su motivo.
**No se les añaden entradas**: una ruta nueva se ajusta a la convención. Cuando
una congelada se migra (o se retira), su entrada se borra y la lista encoge;
una entrada que ya cumple, o que ya no existe, también falla, para que la lista
describa la API real.

Se lee de ``app.openapi()`` con ``ENV=dev`` y ``APP_PROFILE=api``, como
``scripts/check_api_surface.py``.

Uso::

    ENV=dev APP_PROFILE=api python scripts/check_api_convencion.py
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]

_METODOS = ("get", "put", "post", "delete", "patch")
_PARAMS_DE_PAGINA = frozenset({"offset", "cursor", "page", "page_size", "skip"})
_PARAMS_FUERA_DE_CONVENCION = frozenset({"cursor", "page", "page_size", "skip"})
_PREFIJO_PAGINA = "PaginatedResponse_"
_REF_PROBLEMA = "#/components/schemas/ProblemDetail"
_MEDIA_PROBLEMA = "application/problem+json"
_CONSTRUCTORES_DE_RESPUESTA = frozenset({"Response", "JSONResponse", "ORJSONResponse"})

# ── Salidas heredadas (solo encogen) ─────────────────────────────────────────
# Formato: ``"MÉTODO /ruta": "por qué sigue así"``. Migrar cualquiera cambia el
# nombre del componente OpenAPI o la forma de la respuesta, y el frontend las
# consume (``web/src/lib/api-types.ts``): es un cambio incompatible que pide su
# RFC (AGENTS.md §5), no un retoque. Ver «Rutas fuera de la convención» en
# ``docs/api-design.md``.
PAGINACION_CONGELADA: dict[str, str] = {
    "GET /api/v1/competitive/empresas/{empresa_id}/adjudicaciones": (
        "Sobre propio CompetitiveCompanyAwardsDTO (items+total+offset con la empresa al lado)."
    ),
    "GET /api/v1/competitive/renovaciones": (
        "Sobre propio RenovacionesResult (items + months_ahead, sin total); lo pinta Renovaciones."
    ),
    "GET /api/v1/empresas": (
        "Sobre propio EmpresasListResult; es contrato público y lo usa el censo de la consola."
    ),
    "GET /api/v1/licitaciones/cursor": (
        "Cursor por decisión de la RFC 2026-09-06: sucede al listado por offset en el corpus "
        "entero, que es donde un OFFSET grande cuesta. Es contrato público y la usa /detalle."
    ),
    "GET /api/v1/notifications/alerts": (
        "Sobre propio AlertasPagina (offset con no_leidas al lado); lo consume la campana."
    ),
    "GET /api/v1/organizations/{organization_id}/audit": (
        "Cursor sobre un log append-only (CursorPaginatedResponse_AuditEntryOut_); lo usa "
        "la pantalla de auditoría de la organización."
    ),
    "GET /api/v1/publico/sitemap/entradas": (
        "Lista desnuda con offset y tope 50 000: la consume el sitemap.xml del sitio, que "
        "trocea por su cuenta, no un cliente de la API."
    ),
    "GET /api/v1/pursuits": (
        "Sobre propio PursuitListResponse (items+total+offset con agregados del CRM)."
    ),
    "GET /api/v1/pursuits/{pursuit_id}/comments": (
        "Sobre propio PursuitCommentListResponse; lo consume el hilo de la oportunidad."
    ),
    "GET /api/v1/radar/proximas": (
        "Sobre propio RadarProximasResult (offset con la calidad del Radar al lado)."
    ),
}

#: Respuestas 4xx/5xx/default que el esquema declara con otro cuerpo que
#: ``ProblemDetail``. Clave ``"MÉTODO /ruta código"``.
ERROR_ESQUEMA_CONGELADO: dict[str, str] = {}

#: Llamadas a ``Response``/``JSONResponse`` con código de error (o sin código
#: legible) dentro de ``api/``. Clave ``"fichero::función"``.
ERROR_CODIGO_CONGELADO: dict[str, str] = {
    "api/routes/health.py::readiness": (
        "El 503 del readiness lleva el HealthResponse completo a propósito: el balanceador "
        "y el runbook leen qué dependencia falla, no un problem+json."
    ),
}


# ── Paginación ───────────────────────────────────────────────────────────────


def _nombre_ref(esquema: dict[str, Any]) -> str:
    ref = esquema.get("$ref", "")
    return ref.rsplit("/", 1)[-1] if isinstance(ref, str) else ""


def _esquema_200(operacion: dict[str, Any]) -> dict[str, Any]:
    respuestas = operacion.get("responses", {})
    for codigo in ("200", "201"):
        contenido = respuestas.get(codigo, {}).get("content", {})
        json_ = contenido.get("application/json", {})
        if isinstance(json_.get("schema"), dict):
            esquema: dict[str, Any] = json_["schema"]
            return esquema
    return {}


def _es_sobre_de_listado(esquema: dict[str, Any], componentes: dict[str, Any]) -> bool:
    nombre = _nombre_ref(esquema)
    propiedades = set(componentes.get(nombre, {}).get("properties", {})) if nombre else set()
    return "next_cursor" in propiedades or {"items", "total", "offset"} <= propiedades


def _operaciones(schema: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    for ruta, operaciones in schema.get("paths", {}).items():
        for metodo, operacion in operaciones.items():
            if metodo in _METODOS and isinstance(operacion, dict):
                yield f"{metodo.upper()} {ruta}", operacion


def violaciones_paginacion(schema: dict[str, Any]) -> dict[str, str]:
    """``{operación: qué incumple}`` de las que paginan fuera de la convención."""
    componentes = schema.get("components", {}).get("schemas", {})
    fuera: dict[str, str] = {}
    for clave, operacion in _operaciones(schema):
        params = {
            p.get("name")
            for p in operacion.get("parameters", [])
            if isinstance(p, dict) and p.get("in") == "query"
        }
        esquema = _esquema_200(operacion)
        pagina = bool(params & _PARAMS_DE_PAGINA) or _es_sobre_de_listado(esquema, componentes)
        if not pagina:
            continue
        motivos: list[str] = []
        raros = sorted(str(p) for p in params & _PARAMS_FUERA_DE_CONVENCION)
        if raros:
            motivos.append(f"parámetros {raros} (la convención es limit/offset)")
        if not _nombre_ref(esquema).startswith(_PREFIJO_PAGINA):
            nombre = _nombre_ref(esquema) or esquema.get("type", "sin esquema")
            motivos.append(f"responde {nombre} y no Pagina[T]")
        if motivos:
            fuera[clave] = "; ".join(motivos)
    return fuera


# ── Errores ──────────────────────────────────────────────────────────────────


def violaciones_error_esquema(schema: dict[str, Any]) -> dict[str, str]:
    """``{"MÉTODO /ruta código": qué declara}`` de errores que no son ``ProblemDetail``."""
    fuera: dict[str, str] = {}
    for clave, operacion in _operaciones(schema):
        for codigo, respuesta in operacion.get("responses", {}).items():
            if not (codigo[:1] in {"4", "5"} or codigo == "default"):
                continue
            for media, cuerpo in (respuesta.get("content") or {}).items():
                ref = cuerpo.get("schema", {}).get("$ref") if isinstance(cuerpo, dict) else None
                if media != _MEDIA_PROBLEMA or ref != _REF_PROBLEMA:
                    fuera[f"{clave} {codigo}"] = f"{media} → {ref or 'esquema en línea'}"
    return fuera


def _codigo_de_error(valor: ast.expr) -> bool:
    """``True`` si el ``status_code`` es de error **o no se puede leer**."""
    if isinstance(valor, ast.Constant) and isinstance(valor.value, int):
        return valor.value >= 400
    if isinstance(valor, ast.Attribute) and valor.attr.startswith("HTTP_"):
        try:
            return int(valor.attr.split("_")[1]) >= 400
        except (IndexError, ValueError):
            return True
    return True


def violaciones_error_codigo(raiz: Path = _ROOT) -> dict[str, str]:
    """``{"fichero::función": línea}`` de respuestas de error construidas a mano en ``api/``."""
    fuera: dict[str, str] = {}
    for fichero in sorted((raiz / "api").rglob("*.py")):
        relativo = fichero.relative_to(raiz).as_posix()
        if relativo == "api/errors.py":
            continue
        arbol = ast.parse(fichero.read_text(encoding="utf-8"), filename=relativo)
        for funcion in ast.walk(arbol):
            if not isinstance(funcion, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for nodo in ast.walk(funcion):
                if not isinstance(nodo, ast.Call):
                    continue
                nombre = (
                    nodo.func.id
                    if isinstance(nodo.func, ast.Name)
                    else nodo.func.attr
                    if isinstance(nodo.func, ast.Attribute)
                    else ""
                )
                if nombre not in _CONSTRUCTORES_DE_RESPUESTA:
                    continue
                for kw in nodo.keywords:
                    if kw.arg == "status_code" and _codigo_de_error(kw.value):
                        fuera.setdefault(f"{relativo}::{funcion.name}", f"línea {nodo.lineno}")
    return fuera


# ── Gate ─────────────────────────────────────────────────────────────────────


def cargar_schema() -> dict[str, Any]:
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from api.app import app

    return app.openapi()


def _comparar(
    titulo: str, actuales: dict[str, str], congeladas: dict[str, str], errores: list[str]
) -> None:
    for clave in sorted(set(actuales) - set(congeladas)):
        errores.append(f"[{titulo}] NUEVA salida de la convención: {clave} — {actuales[clave]}")
    for clave in sorted(set(congeladas) - set(actuales)):
        errores.append(
            f"[{titulo}] {clave} ya cumple o ya no existe: borrá su entrada (la lista solo encoge)."
        )


def main(argv: list[str]) -> int:
    del argv
    schema = cargar_schema()
    errores: list[str] = []
    paginacion = violaciones_paginacion(schema)
    esquema = violaciones_error_esquema(schema)
    codigo = violaciones_error_codigo()
    _comparar("paginación", paginacion, PAGINACION_CONGELADA, errores)
    _comparar("error en el esquema", esquema, ERROR_ESQUEMA_CONGELADO, errores)
    _comparar("error en el código", codigo, ERROR_CODIGO_CONGELADO, errores)

    if errores:
        for linea in errores:
            print(linea, file=sys.stderr)
        print(
            "\nConvención de la API (docs/api-design.md): una ruta nueva pagina con "
            "`Depends(pagina())` y responde `Pagina[T]`; un error se lanza con "
            "`HTTPException` y lo formatea el manejador único de api/errors.py como "
            "`ProblemDetail` (application/problem+json). Las listas congeladas de "
            "scripts/check_api_convencion.py no admiten entradas nuevas.",
            file=sys.stderr,
        )
        return 1

    congeladas = len(PAGINACION_CONGELADA) + len(ERROR_ESQUEMA_CONGELADO)
    congeladas += len(ERROR_CODIGO_CONGELADO)
    print(f"Convención de la API OK ({congeladas} salidas heredadas congeladas).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
