"""Tools de esquema: ``describir_esquema`` y ``describir_tabla`` (más el glosario).

Dan al LLM el mapa antes de escribir SQL: qué tablas ve, qué significan sus
columnas y las trampas del dominio (``glosario.md``, escrito a mano).

El nombre de tabla de ``describir_tabla`` se valida **contra el catálogo** antes
de tocar SQL (comparación exacta: ``Users`` o ``users"; --`` no coinciden con
nada). Las columnas se filtran dos veces: el rol solo ve las que tienen
``SELECT`` y, en las tablas con columnas ocultas, solo se muestran las
``columnas_permitidas`` del catálogo.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import Annotated, TypedDict

from pydantic import Field

from db.consulta_libre import (
    JSONValue,
    ResultadoConsulta,
    claves_foraneas_de,
    columnas_de,
    ejemplo_de,
    filas_aproximadas,
)
from mcp_server.catalogo import (
    DOMINIOS,
    EntradaCatalogo,
    Visibilidad,
    entrada_visible,
    tablas_visibles,
)
from mcp_server.tools import ErrorHerramienta
from mcp_server.tools.consulta import SalidaConsulta

__all__ = [
    "SalidaDescribirEsquema",
    "SalidaDescribirTabla",
    "describir_esquema",
    "describir_tabla",
    "ejemplos_sql_del_glosario",
    "glosario",
]


class _Tabla(TypedDict):
    tabla: str
    descripcion: str
    filas_aprox: int


class _Dominio(TypedDict):
    dominio: str
    tablas: list[_Tabla]


class SalidaDescribirEsquema(TypedDict):
    dominios: list[_Dominio]
    glosario: str


class _Columna(TypedDict):
    nombre: str
    tipo: str
    nulo: bool


class _ClaveForanea(TypedDict):
    columna: str
    tabla_destino: str
    columna_destino: str


class SalidaDescribirTabla(TypedDict):
    tabla: str
    dominio: str
    descripcion: str
    columnas: list[_Columna]
    claves_foraneas: list[_ClaveForanea]
    ejemplo: SalidaConsulta


_RUTA_GLOSARIO = Path(__file__).resolve().parent.parent / "glosario.md"
_BLOQUE_SQL = re.compile(r"^```sql\n(.*?)^```", re.DOTALL | re.MULTILINE)
#: Tope del nombre que se repite en el mensaje de error (un nombre hostil puede ser enorme).
_MAX_ECO = 60


@cache
def glosario() -> str:
    """Texto del glosario de negocio; se lee una sola vez."""
    return _RUTA_GLOSARIO.read_text(encoding="utf-8")


def ejemplos_sql_del_glosario() -> list[str]:
    """Los bloques ```sql del glosario, para comprobar que siguen siendo válidos."""
    return [m.group(1).strip() for m in _BLOQUE_SQL.finditer(glosario())]


def describir_esquema() -> dict[str, JSONValue]:
    """Mapa de la base de datos: tablas visibles por dominio, más el glosario de negocio.

    Llámala antes de escribir SQL. Cada tabla trae una línea de descripción y
    sus filas aproximadas (``filas_aprox``, de las estadísticas de Postgres).
    El ``glosario`` explica las trampas del dominio: qué fila contar cuando una
    licitación llega por varias fuentes, qué base lleva cada importe, los
    valores de ``estado``, las claves de unión y ejemplos de SQL válidos.

    Devuelve ``{"dominios": [{"dominio", "tablas": [{"tabla", "descripcion",
    "filas_aprox"}, ...]}, ...], "glosario": "..."}``. Las columnas de una
    tabla se ven con ``describir_tabla``.
    """
    visibles = tablas_visibles()
    filas = filas_aproximadas([e.tabla for e in visibles])
    dominios: list[JSONValue] = []
    for dominio in DOMINIOS:
        tablas: list[JSONValue] = [
            {"tabla": e.tabla, "descripcion": e.descripcion, "filas_aprox": filas.get(e.tabla, 0)}
            for e in visibles
            if e.dominio == dominio
        ]
        if tablas:
            dominios.append({"dominio": dominio, "tablas": tablas})
    return {"dominios": dominios, "glosario": glosario()}


def _columnas_visibles(entrada: EntradaCatalogo) -> list[dict[str, str | bool]]:
    columnas = columnas_de(entrada.tabla)
    if entrada.visibilidad is Visibilidad.COLUMNAS_EXCLUIDAS:
        permitidas = set(entrada.columnas_permitidas)
        columnas = [c for c in columnas if c["nombre"] in permitidas]
    return columnas


def describir_tabla(
    tabla: Annotated[
        str,
        Field(
            description="Nombre exacto de una tabla de describir_esquema, en minúsculas. "
            "Ejemplo: 'licitaciones'"
        ),
    ],
) -> dict[str, JSONValue]:
    """Columnas, claves foráneas y 3 filas de ejemplo de una tabla visible.

    Úsala para saber qué columnas puede leer ``consultar_sql`` en una tabla y
    cómo se une con otras. Solo se muestran las columnas visibles para el MCP
    (las sensibles no aparecen) y solo las claves foráneas hacia tablas que
    también lo son.

    Devuelve ``{"tabla", "dominio", "descripcion", "columnas": [{"nombre",
    "tipo", "nulo"}, ...], "claves_foraneas": [{"columna", "tabla_destino",
    "columna_destino"}, ...], "ejemplo": {"columnas", "filas", ...}}``. Un
    nombre que no está en el catálogo es un error que lista las tablas válidas.
    """
    entrada = entrada_visible(tabla)
    if entrada is None:
        eco = tabla if len(tabla) <= _MAX_ECO else f"{tabla[:_MAX_ECO]}…"
        validas = ", ".join(e.tabla for e in tablas_visibles())
        raise ErrorHerramienta(
            f"La tabla {eco!r} no existe o no es visible.",
            f"Usa describir_esquema para ver las tablas disponibles. Válidas: {validas}.",
        )
    columnas = _columnas_visibles(entrada)
    nombres = [str(c["nombre"]) for c in columnas]
    claves: list[JSONValue] = [
        {
            "columna": fk["columna"],
            "tabla_destino": fk["tabla_destino"],
            "columna_destino": fk["columna_destino"],
        }
        for fk in claves_foraneas_de(entrada.tabla)
        # Solo FK sobre columnas mostradas y hacia tablas que el MCP también ve.
        if fk["columna"] in nombres and entrada_visible(fk["tabla_destino"]) is not None
    ]
    ejemplo = (
        ejemplo_de(entrada.tabla, nombres)
        if nombres
        else ResultadoConsulta(columnas=[], filas=[], n_filas=0, truncado=False, duracion_ms=0)
    )
    columnas_json: list[JSONValue] = [
        {"nombre": c["nombre"], "tipo": c["tipo"], "nulo": c["nulo"]} for c in columnas
    ]
    return {
        "tabla": entrada.tabla,
        "dominio": entrada.dominio,
        "descripcion": entrada.descripcion,
        "columnas": columnas_json,
        "claves_foraneas": claves,
        "ejemplo": ejemplo.como_dict(),
    }
