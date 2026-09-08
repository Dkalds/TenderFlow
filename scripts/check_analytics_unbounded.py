"""Ningún método analítico devuelve el resultado entero sin cota (C3.2).

`rows_to_dicts(cursor)` materializa **todas** las filas del cursor en memoria.
En una consulta con `LIMIT` eso es una página; sin él, es la tabla. El OOM del
2026-08-02 salió de ahí, y ADR-023 fijó la regla —agregar en SQL, no escanear en
proceso— sin dejar nada que la comprobara para los caminos que quedaban.

Este escáner recorre el grafo de llamadas desde `api/routes/analytics.py` hasta
`db/repositories/*` y marca cada método alcanzable que llame a `rows_to_dicts`
sobre una consulta sin cota.

**Qué cuenta como cota**, en orden de preferencia:

1. Un `LIMIT` literal o parametrizado en el SQL del método.
2. Un `WHERE` sobre clave primaria o un `= %s` sobre una columna de identidad
   (leer una fila por id no necesita `LIMIT`).
3. Una agregación (`GROUP BY`, `COUNT(`, `SUM(`) cuya cardinalidad la acota el
   propio agrupamiento — un `GROUP BY ccaa` devuelve 19 filas, no 400.000.

Es un ratchet con allowlist decreciente, como TID251: las violaciones vivas
están enumeradas abajo y la lista **solo puede encoger**.

Uso::

    python scripts/check_analytics_unbounded.py
    python scripts/check_analytics_unbounded.py --verbose
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ROUTER = _REPO_ROOT / "api" / "routes" / "analytics.py"
_SERVICIOS = _REPO_ROOT / "services" / "analytics"
_REPOSITORIOS = _REPO_ROOT / "db" / "repositories"

#: Violaciones vivas el 2026-09-06. **Solo puede encoger.**
#:
#: Formato `fichero::metodo`. Añadir una entrada es declarar que se introduce un
#: escaneo sin cota alcanzable desde la analítica: una decisión explícita, no un
#: descuido.
#:
#: Ninguna de estas ocho se arregla con un `LIMIT` puesto encima: todas acotan
#: hoy por filtro (órgano, ventana de fechas, estado abierto) y ponerles un tope
#: constante **truncaría el resultado en silencio** — un Radar con 300 de 400
#: candidatas, un forecast sobre media serie. Lo que piden es o bien agregar en
#: SQL (ADR-023) o bien una cota con `truncado: true` declarado en la respuesta,
#: y las dos cosas cambian comportamiento que solo la suite de integración
#: contra Postgres puede validar.
#:
#: `tecnologia_detalle_items` salió de esta lista el 2026-09-06: tenía un
#: `limit` que se aplicaba en Python después de materializarlo todo, así que
#: bajarlo al SQL fue equivalencia exacta y no una decisión de producto.
ALLOWLIST: frozenset[str] = frozenset(
    {
        # Filas de adjudicación de UN órgano y de UN patrón de UTE. Acotadas por
        # el filtro; el techo real es cuántas adjudicaciones tiene el órgano más
        # grande. Camino 2 de ADR-026 (SQL acotado + pandas), que exige LIMIT y
        # alcance declarado: pendiente de ese contrato de respuesta.
        "adjudicaciones.py::load_por_organo",
        "adjudicaciones.py::load_ute_rows",
        # Serie histórica completa para el forecast. Un LIMIT aquí recorta la
        # serie por un extremo y sesga la predicción.
        "aggregates.py::adjudicaciones_para_forecast",
        "aggregates.py::retendering_universe",
        # Proyecciones acotadas por filtro (un órgano, una ventana de fechas).
        "aggregates.py::licitaciones_por_organo",
        "aggregates.py::pipeline_window",
        # El universo puntuable del Radar. Truncarlo es truncar el Radar, así
        # que su cota tiene que venir con `truncado` en la respuesta.
        "aggregates.py::scoring_candidates",
        # `SELECT … FROM predicciones_baja` sin WHERE, a propósito: el modo
        # page-aligned del Detalle necesita el p50 de todas las puntuadas. Crece
        # con el modelo, no con el corpus, y el job de ML ya la purga por
        # antigüedad.
        "predicciones.py::baja_p50_con_origen",
    }
)

_COTA_EN_SQL = re.compile(
    r"\bLIMIT\b|\bGROUP\s+BY\b|\bCOUNT\s*\(|\bSUM\s*\(|\bAVG\s*\(|"
    r"\bMAX\s*\(|\bMIN\s*\(|\bfetchone\b",
    re.I,
)
#: Lectura acotada por identidad. Cubre tres formas, y las tres las acota el
#: argumento de quien llama, no el tamaño de la tabla:
#:
#: - `WHERE licitacion_id = %s` — una fila.
#: - `WHERE id_externo IN (%s, %s, …)` — tantas como ids se pasen.
#: - `WHERE a.id = %s` — con alias de tabla.
_POR_IDENTIDAD = re.compile(
    r"WHERE\s+[\w.\"]*\w*id\w*\s*(?:=\s*%s|IN\s*\()",
    re.I,
)


def _literales_de_cadena(nodo: ast.AST) -> str:
    """Concatena todas las cadenas literales del subárbol.

    El SQL se construye por concatenación implícita y por f-string, así que
    reconstruirlo entero no es posible; lo que se busca es si en alguna parte
    de esa construcción aparece una cota, que sí sobrevive a la concatenación.
    """
    trozos: list[str] = []
    for hijo in ast.walk(nodo):
        if isinstance(hijo, ast.Constant) and isinstance(hijo.value, str):
            trozos.append(hijo.value)
        elif isinstance(hijo, ast.JoinedStr):
            for parte in hijo.values:
                if isinstance(parte, ast.Constant) and isinstance(parte.value, str):
                    trozos.append(parte.value)
    return " ".join(trozos)


def _usa_rows_to_dicts(nodo: ast.AST) -> bool:
    for hijo in ast.walk(nodo):
        if isinstance(hijo, ast.Call):
            fn = hijo.func
            nombre = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if nombre == "rows_to_dicts":
                return True
    return False


def _metodos_de(fichero: Path) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    arbol = ast.parse(fichero.read_text(encoding="utf-8"))
    salida: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.FunctionDef | ast.AsyncFunctionDef):
            salida[nodo.name] = nodo
    return salida


def _nombres_llamados(fichero: Path) -> set[str]:
    """Nombres de función/método invocados en *fichero*, sin resolver el receptor.

    Resolver el tipo del receptor exigiría inferencia; para lo que hace falta
    aquí —saber si `api/routes/analytics.py` puede acabar en `X.metodo`— basta
    el nombre, y errar por exceso es lo correcto en un control de este tipo.
    """
    arbol = ast.parse(fichero.read_text(encoding="utf-8"))
    nombres: set[str] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Call):
            fn = nodo.func
            nombre = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if nombre:
                nombres.add(nombre)
    return nombres


def alcanzables_desde_la_analitica() -> set[str]:
    """Nombres invocados por el router de analítica y sus servicios."""
    nombres = _nombres_llamados(_ROUTER)
    for servicio in sorted(_SERVICIOS.glob("*.py")):
        nombres |= _nombres_llamados(servicio)
    return nombres


def sin_cota() -> list[tuple[str, str]]:
    """Devuelve `(fichero, metodo)` de cada escaneo sin cota alcanzable."""
    alcanzables = alcanzables_desde_la_analitica()
    hallazgos: list[tuple[str, str]] = []

    for repo in sorted(_REPOSITORIOS.glob("*.py")):
        if repo.name == "base.py":
            continue
        for nombre, nodo in _metodos_de(repo).items():
            if nombre.startswith("_") or nombre not in alcanzables:
                continue
            if not _usa_rows_to_dicts(nodo):
                continue
            sql = _literales_de_cadena(nodo)
            if _COTA_EN_SQL.search(sql) or _POR_IDENTIDAD.search(sql):
                continue
            hallazgos.append((repo.name, nombre))
    return hallazgos


def main() -> int:
    verbose = "--verbose" in sys.argv
    hallazgos = sin_cota()
    claves = {f"{fichero}::{metodo}" for fichero, metodo in hallazgos}

    nuevos = sorted(claves - ALLOWLIST)
    resueltos = sorted(ALLOWLIST - claves)

    if resueltos:
        print(f"Entradas de la allowlist que ya no hacen falta (quitalas del script): {resueltos}")

    if nuevos:
        print(
            f"\n{len(nuevos)} método/s alcanzable/s desde la analítica que "
            "materializan un resultado sin cota:\n",
            file=sys.stderr,
        )
        for clave in nuevos:
            print(f"  - {clave}", file=sys.stderr)
        print(
            "\nAgregá en SQL (ADR-023) o acotá con LIMIT. Si el escaneo es "
            "deliberado y está justificado, la decisión va en la allowlist de "
            "este script con su motivo.",
            file=sys.stderr,
        )
        return 1

    if verbose:
        print(f"Nombres alcanzables desde la analítica: {len(alcanzables_desde_la_analitica())}")
    print(
        f"OK: ningún método analítico materializa sin cota "
        f"({len(ALLOWLIST)} excepción/es declarada/s)."
    )
    return 0 if not resueltos else 1


if __name__ == "__main__":
    sys.exit(main())
