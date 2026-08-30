#!/usr/bin/env python3
"""Verifica que la superficie **pública** no exponga analítica propia ni datos personales.

Contexto (2026-08, al abrir la superficie pública indexable): la decisión de
producto es publicar **solo el dato base** del anuncio oficial —que ya es open
data de PLACSP y TED— y dejar detrás del login todo lo derivado del pipeline
propio. El problema es que las piezas que una página pública llamaría por
instinto **ya arrastran** esos campos:

- ``LicitacionRepository.get_by_id`` es un ``SELECT *`` (db/repositories/licitaciones.py),
  así que devuelve ``ml_proba``, ``inclusion_reason``, ``filter_version``… enteros.
- ``_SUMMARY_COLS`` y el DTO ``LicitacionSummary`` de ``api/routes/licitaciones.py``
  incluyen ``ml_tecnologias``, ``ml_proba_max`` y ``ml_tech_principal``.

O sea que la fuga no requiere un error de diseño: basta con reutilizar lo que ya
hay. Y no falla nada — el endpoint responde 200 y el campo de más viaja en el
JSON sin que nadie lo mire. Este guard es la red que convierte esa fuga
silenciosa en un fallo de CI.

Dos denylists, por motivos distintos:

``analitica``
    Propiedad intelectual del producto. ``raw_keywords`` es literalmente el
    diccionario propietario en claro y ``filter_version`` su hash (delata
    cuándo cambia). Ojo con ``tecnologia``: **parece** dato de fuente y no lo
    es — lo construye el parser con el diccionario propio.

``pii``
    ``adjudicaciones.nif`` puede ser el DNI de un autónomo y ``nombre`` su
    nombre y apellidos: en el repo **no existe** ninguna lógica que distinga
    persona física de jurídica (``es_pyme`` no sirve: viene de
    ``SMEAwardedIndicator`` y marca a cualquier empresa pequeña). Hasta que
    exista un clasificador que falle cerrado, estos campos no salen.

Lo que este guard NO cubre, y conviene tener presente: la **selección misma del
corpus** es propietaria. ``scraper/codice_parser.py:551`` descarta el expediente
que no casa con el diccionario, así que la lista de qué se publica y qué no
reconstruye el diccionario por diferencia contra el PLACSP público. Eso es una
decisión de producto, no algo que una allowlist de columnas pueda arreglar.

Uso::

    python scripts/check_public_surface.py
    python scripts/check_public_surface.py --strict

Allowlist por línea: añadí ``cps-allow`` (o ``cps-allow:categoria``) en un
comentario de la línea, con el motivo. Como en
``scripts/check_frontend_invariants.py``, del que este guard copia la forma.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

# ── Qué se escanea ────────────────────────────────────────────────────────
# Los árboles que sirven tráfico anónimo. Se listan explícitamente en vez de
# escanear todo el repo: el dashboard privado usa estos campos con todo el
# derecho, y un guard que grite ahí sería ruido que acaba desactivado.
#
# La lista incluye los módulos de `web/src/lib/` que componen lo que se publica,
# y no solo el árbol de rutas. El motivo es un precedente del propio repo: el
# escáner de deduplicación (`tests/test_dedup_guardrail.py`) se desactivaba solo
# porque las olas del ratchet TID251 movían el SQL fuera de su radio —sin fallo,
# sin aviso y con el commit de la migración en verde—. Aquí pasaría lo mismo en
# cuanto alguien extrajera una pieza de `(publico)/` a `lib/`, que es
# exactamente el refactor que el repo promueve.
#
# **Al mover código de `(publico)/` a `lib/`, añadilo aquí en el mismo cambio.**
SCAN_TARGETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("api/routes", (".py",)),  # filtrado a los módulos públicos, ver _es_publico
    ("db/repositories/publico.py", (".py",)),  # donde vive la allowlist de columnas
    ("web/src/app/(publico)", (".ts", ".tsx")),
    # Rutas de metadatos que sirven tráfico anónimo desde fuera de `(publico)/`.
    ("web/src/app/sitemap.ts", (".ts",)),
    ("web/src/app/sitemap-index.xml", (".ts",)),
    ("web/src/app/robots.ts", (".ts",)),
    ("web/src/app/opengraph-image.tsx", (".tsx",)),
    # Composición del dato público: `jsonld` serializa datos estructurados con
    # `dangerouslySetInnerHTML` y `publico-api` declara los tipos que consume la
    # superficie. Un campo prohibido llega a la página por cualquiera de los dos.
    ("web/src/lib/jsonld.ts", (".ts",)),
    ("web/src/lib/publico-api.ts", (".ts",)),
    ("web/src/lib/slug.ts", (".ts",)),
    ("web/src/lib/site.ts", (".ts",)),
)

# Dentro de api/routes/ solo son públicos los módulos con este prefijo. El
# resto exige sesión o API key y queda fuera del escaneo.
PREFIJO_MODULO_PUBLICO = "publico"

SKIP_DIR_PARTS: frozenset[str] = frozenset({"node_modules", ".next", "__pycache__", "__tests__"})
SKIP_FILE_MARKERS: tuple[str, ...] = (".test.", ".spec.")
ALLOW_MARKER = "cps-allow"

CATEGORIES: tuple[str, ...] = ("analitica", "pii")

# ── Denylists ─────────────────────────────────────────────────────────────
# Identificadores exactos de columna. Se comparan con `\b` para no cazar
# subcadenas inocentes (p.ej. `tecnologias_pliego` no es `tecnologia`).
CAMPOS_ANALITICA: tuple[str, ...] = (
    "ml_proba",
    "ml_proba_max",
    "ml_tecnologias",
    "ml_tech_principal",
    "tecnologia",  # NO es dato de fuente: lo construye el parser propio
    "raw_keywords",  # el diccionario propietario en claro
    "filter_version",  # hash de TECHNOLOGY_KEYWORDS: delata cuándo cambia
    "classifier_model_version",
    "inclusion_reason",  # 'keyword' | 'ml_cpv_rescue': revela la estrategia
    "analysis_universe",
)

CAMPOS_PII: tuple[str, ...] = (
    "nif",
    "importe_pagable",
    "oferta_minima",
    "oferta_maxima",
)

# `SELECT *` sobre las tablas de negocio: la vía más directa a una fuga, porque
# arrastra las columnas ML sin nombrarlas y por tanto sin activar la denylist.
_RE_SELECT_ESTRELLA = re.compile(
    r"SELECT\s+\*\s+FROM\s+(licitaciones|adjudicaciones)", re.IGNORECASE
)

# Reutilizar estas piezas en una ruta pública filtra por construcción.
_RE_REUTILIZACION_INSEGURA = re.compile(r"\b(get_by_id|_SUMMARY_COLS(?:_STR)?)\b")


def _regex_campos(campos: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(r"\b(" + "|".join(re.escape(c) for c in campos) + r")\b")


PATRONES: dict[str, tuple[re.Pattern[str], ...]] = {
    "analitica": (
        _regex_campos(CAMPOS_ANALITICA),
        _RE_SELECT_ESTRELLA,
        _RE_REUTILIZACION_INSEGURA,
    ),
    "pii": (_regex_campos(CAMPOS_PII),),
}


@dataclass(frozen=True)
class Hallazgo:
    categoria: str
    fichero: Path
    linea: int
    texto: str


def _es_comentario(linea: str, suffix: str) -> bool:
    limpia = linea.strip()
    if suffix == ".py":
        return limpia.startswith("#")
    return limpia.startswith(("//", "*", "/*"))


def _lineas_de_docstring(contenido: str) -> frozenset[int]:
    """Números de línea ocupados por docstrings en un módulo Python.

    Hacen falta porque los ficheros de la superficie pública **explican en su
    docstring** qué campos quedan fuera y por qué, nombrándolos: sin esta
    exención, documentar la regla la incumpliría.

    Se resuelve con ``ast`` y no descartando todo lo que vaya entre comillas
    triples, que sería lo fácil. La diferencia importa: una consulta SQL
    escrita en una cadena de comillas triples —un patrón perfectamente normal—
    quedaría exenta con el atajo, y ahí es exactamente donde una fuga pasaría
    inadvertida. Aquí solo se exime el docstring de módulo, clase o función.

    Un fichero que no parsea devuelve el conjunto vacío: se escanea entero. Es
    la opción conservadora — ante la duda, más ruido y no menos.
    """
    try:
        arbol = ast.parse(contenido)
    except SyntaxError:
        return frozenset()

    lineas: set[int] = set()
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        cuerpo = getattr(nodo, "body", None)
        if not cuerpo:
            continue
        primero = cuerpo[0]
        if (
            isinstance(primero, ast.Expr)
            and isinstance(primero.value, ast.Constant)
            and isinstance(primero.value.value, str)
            and primero.end_lineno is not None
        ):
            lineas.update(range(primero.lineno, primero.end_lineno + 1))
    return frozenset(lineas)


def _es_publico(ruta: Path) -> bool:
    """En ``api/routes/`` solo se escanean los módulos del router público."""
    if ruta.suffix != ".py":
        return True
    if ruta.parent.name != "routes":
        return True
    return ruta.stem.startswith(PREFIJO_MODULO_PUBLICO)


def _ficheros() -> list[Path]:
    encontrados: list[Path] = []
    for subruta, sufijos in SCAN_TARGETS:
        raiz = REPO_ROOT / subruta
        if not raiz.exists():
            continue
        if raiz.is_file():
            encontrados.append(raiz)
            continue
        for ruta in raiz.rglob("*"):
            if not ruta.is_file() or ruta.suffix not in sufijos:
                continue
            if SKIP_DIR_PARTS & set(ruta.parts):
                continue
            if any(m in ruta.name for m in SKIP_FILE_MARKERS):
                continue
            if not _es_publico(ruta):
                continue
            encontrados.append(ruta)
    return sorted(encontrados)


def _escanear(ruta: Path) -> list[Hallazgo]:
    hallazgos: list[Hallazgo] = []
    try:
        contenido = ruta.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return hallazgos

    docstrings = _lineas_de_docstring(contenido) if ruta.suffix == ".py" else frozenset()

    for n, linea in enumerate(contenido.splitlines(), start=1):
        if ALLOW_MARKER in linea:
            continue
        if n in docstrings:
            continue
        if _es_comentario(linea, ruta.suffix):
            continue
        for categoria, patrones in PATRONES.items():
            if any(p.search(linea) for p in patrones):
                hallazgos.append(
                    Hallazgo(categoria, ruta.relative_to(REPO_ROOT), n, linea.strip()[:120])
                )
    return hallazgos


def _informar(hallazgos: list[Hallazgo]) -> None:
    print("--- Superficie publica: analitica propia y datos personales ---")
    if not hallazgos:
        ficheros = len(_ficheros())
        print(f"[OK] Sin hallazgos en {ficheros} fichero(s) de superficie publica.")
        return

    for categoria in CATEGORIES:
        del_cat = [h for h in hallazgos if h.categoria == categoria]
        if not del_cat:
            continue
        print(f"\n[{categoria}] {len(del_cat)} hallazgo(s):")
        for h in del_cat:
            print(f"  {h.fichero}:{h.linea}")
            print(f"    {h.texto}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="exit 1 ante cualquier hallazgo")
    parser.add_argument("--error-category", action="append", choices=CATEGORIES, default=[])
    args = parser.parse_args()

    hallazgos = [h for ruta in _ficheros() for h in _escanear(ruta)]
    _informar(hallazgos)

    categorias_que_fallan = set(args.error_category) or (set(CATEGORIES) if args.strict else set())
    if any(h.categoria in categorias_que_fallan for h in hallazgos):
        print(
            "\nLa superficie publica no puede exponer analitica propia ni datos "
            f"personales. Corregi con una proyeccion por allowlist, o justifica la "
            f"linea con '{ALLOW_MARKER}:<categoria>'."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
