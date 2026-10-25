"""Ratchet de la convención de la API (``scripts/check_api_convencion.py``).

Una ruta nueva pagina con ``Pagina[T]`` (limit/offset) y sus errores salen como
``ProblemDetail``; las salidas heredadas están congeladas y solo encogen. El
check real corre en un proceso aparte con ``ENV=dev`` y ``APP_PROFILE=api``,
como el de superficie, porque el esquema depende de qué routers se montan.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "check_api_convencion.py"


def _cargar_modulo():
    spec = importlib.util.spec_from_file_location("check_api_convencion", _SCRIPT)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["check_api_convencion"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture()
def convencion():
    return _cargar_modulo()


def _ref(nombre: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{nombre}"}


def _op(respuesta: str, *params: str, errores: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "parameters": [{"name": p, "in": "query"} for p in params],
        "responses": {
            "200": {"content": {"application/json": {"schema": _ref(respuesta)}}},
            **(errores or {}),
        },
    }


_COMPONENTES = {
    "PaginatedResponse_X_": {"properties": {"items": {}, "total": {}, "limit": {}, "offset": {}}},
    "CursorPaginatedResponse_X_": {"properties": {"items": {}, "next_cursor": {}}},
    "SobrePropio": {"properties": {"items": {}, "total": {}, "offset": {}}},
    "ListaCompleta": {"properties": {"items": {}, "total": {}}},
    "Ficha": {"properties": {"id": {}}},
}


def _schema(**rutas: dict[str, Any]) -> dict[str, Any]:
    return {
        "paths": {ruta: {"get": op} for ruta, op in rutas.items()},
        "components": {"schemas": _COMPONENTES},
    }


def test_la_api_de_hoy_pasa_el_gate():
    """El check corrido de verdad contra la app: es lo que CI ejecuta."""
    entorno = {**os.environ, "ENV": "dev", "APP_PROFILE": "api", "PYTHONUTF8": "1"}
    proceso = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        cwd=_ROOT,
        env=entorno,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=300,
    )

    assert proceso.returncode == 0, proceso.stderr[-4000:]
    assert "Convención de la API OK" in proceso.stdout


# ── Paginación ───────────────────────────────────────────────────────────────


def test_pagina_por_offset_cumple(convencion):
    schema = _schema(**{"/a": _op("PaginatedResponse_X_", "limit", "offset")})

    assert convencion.violaciones_paginacion(schema) == {}


def test_una_ficha_o_una_lista_completa_no_paginan(convencion):
    """``items`` + ``total`` sin ventana es una lista entera, no una página."""
    schema = _schema(**{"/a": _op("Ficha"), "/b": _op("ListaCompleta", "limit")})

    assert convencion.violaciones_paginacion(schema) == {}


def test_un_cursor_nuevo_es_una_salida(convencion):
    schema = _schema(**{"/a": _op("CursorPaginatedResponse_X_", "cursor", "limit")})

    fuera = convencion.violaciones_paginacion(schema)

    assert list(fuera) == ["GET /a"]
    assert "cursor" in fuera["GET /a"]


def test_un_sobre_propio_con_offset_es_una_salida(convencion):
    schema = _schema(**{"/a": _op("SobrePropio", "limit", "offset")})

    assert "SobrePropio" in convencion.violaciones_paginacion(schema)["GET /a"]


def test_una_pagina_con_page_en_vez_de_offset_es_una_salida(convencion):
    schema = _schema(**{"/a": _op("PaginatedResponse_X_", "page", "limit")})

    assert "page" in convencion.violaciones_paginacion(schema)["GET /a"]


# ── Errores ──────────────────────────────────────────────────────────────────


def test_un_error_problem_json_cumple(convencion):
    problema = {"content": {"application/problem+json": {"schema": _ref("ProblemDetail")}}}
    schema = _schema(**{"/a": _op("Ficha", errores={"404": problema, "default": problema})})

    assert convencion.violaciones_error_esquema(schema) == {}


def test_un_error_con_otro_cuerpo_es_una_salida(convencion):
    otro = {"content": {"application/json": {"schema": _ref("MiError")}}}
    schema = _schema(**{"/a": _op("Ficha", errores={"409": otro})})

    assert list(convencion.violaciones_error_esquema(schema)) == ["GET /a 409"]


def test_una_respuesta_de_error_a_mano_es_una_salida(convencion, tmp_path):
    rutas = tmp_path / "api" / "routes"
    rutas.mkdir(parents=True)
    (tmp_path / "api" / "errors.py").write_text(
        "def f():\n    return JSONResponse(status_code=500, content={})\n", encoding="utf-8"
    )
    (rutas / "cosas.py").write_text(
        "from fastapi import status\n"
        "def creada():\n    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content={})\n"
        "def mala():\n    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={})\n"
        "def opaca(c):\n    return Response(status_code=c)\n",
        encoding="utf-8",
    )

    fuera = convencion.violaciones_error_codigo(tmp_path)

    # api/errors.py es el manejador único: es el sitio donde sí se construyen.
    assert sorted(fuera) == ["api/routes/cosas.py::mala", "api/routes/cosas.py::opaca"]


# ── El ratchet solo encoge ───────────────────────────────────────────────────


@pytest.fixture()
def simulada(convencion, monkeypatch):
    schema = _schema(**{"/vieja": _op("SobrePropio", "offset")})
    monkeypatch.setattr(convencion, "cargar_schema", lambda: schema)
    monkeypatch.setattr(convencion, "violaciones_error_codigo", dict)
    monkeypatch.setattr(convencion, "PAGINACION_CONGELADA", {"GET /vieja": "heredada"})
    monkeypatch.setattr(convencion, "ERROR_ESQUEMA_CONGELADO", {})
    monkeypatch.setattr(convencion, "ERROR_CODIGO_CONGELADO", {})
    return convencion, schema


def test_una_salida_congelada_pasa(simulada, capsys):
    convencion, _ = simulada

    assert convencion.main([]) == 0
    assert "1 salidas heredadas" in capsys.readouterr().out


def test_una_salida_nueva_falla_y_explica_la_convencion(simulada, capsys):
    convencion, schema = simulada
    schema["paths"]["/nueva"] = {"get": _op("CursorPaginatedResponse_X_", "cursor")}

    assert convencion.main([]) == 1
    error = capsys.readouterr().err
    assert "GET /nueva" in error
    assert "docs/api-design.md" in error


def test_una_congelada_que_ya_cumple_obliga_a_borrar_su_entrada(simulada, capsys):
    convencion, schema = simulada
    schema["paths"]["/vieja"] = {"get": _op("PaginatedResponse_X_", "limit", "offset")}

    assert convencion.main([]) == 1
    assert "GET /vieja ya cumple" in capsys.readouterr().err


def test_las_congeladas_reales_llevan_motivo(convencion):
    todas = {
        **convencion.PAGINACION_CONGELADA,
        **convencion.ERROR_ESQUEMA_CONGELADO,
        **convencion.ERROR_CODIGO_CONGELADO,
    }

    assert all(len(motivo.strip()) >= 40 for motivo in todas.values())
