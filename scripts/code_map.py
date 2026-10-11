#!/usr/bin/env python3
"""Mapa del código Python desde el AST: dónde se define algo y quién lo usa.

Es el paso 2 de AGENTS.md §1: lo que consulta un agente que no tiene el CLI
``graphify`` (todas las sesiones remotas, CI, Codex y OpenCode sin instalación
local). Solo usa la biblioteca estándar, lee el árbol tal como está en disco
—no hay artefacto que pueda quedarse viejo— y tarda unos segundos.

Sustituye a los artefactos de ``graphify-out/`` que se versionaban hasta
2026-10: ``graph.json`` pesaba 51 MB, llevaba decenas de commits de retraso y
ningún agente podía leerlo entero; en la práctica el «fallback» era buscar
texto. Esto contesta las tres preguntas para las que se abría el grafo.

Uso::

    python scripts/code_map.py simbolo upsert_licitaciones   # definición y usos
    python scripts/code_map.py importadores db.upsert        # quién importa el módulo
    python scripts/code_map.py paquete services/rag          # módulos y su API pública
    python scripts/code_map.py fichero api/routes/ask.py     # esquema e imports del repo

Límites, a propósito: solo Python (para ``web/`` sirve el propio TypeScript:
``npx tsc --noEmit`` y la búsqueda de texto), solo imports estáticos, y los
usos de un símbolo se buscan en los ficheros que importan su módulo. No resuelve
despacho dinámico ni ``getattr``.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

#: Directorios que nunca son código del proyecto.
_EXCLUIDOS = (".venv", "node_modules", "graphify-out", ".claude", ".agents", "build", "dist")


@dataclass(frozen=True)
class Definicion:
    """Una clase, función o método, con su posición."""

    nombre: str
    tipo: str
    fichero: str
    linea: int


@dataclass
class Modulo:
    """Lo que se extrae de un fichero ``.py``."""

    fichero: str
    nombre: str
    lineas: int
    resumen: str
    definiciones: list[Definicion] = field(default_factory=list)
    #: Módulo importado → nombres traídos con ``from … import`` (vacío si es
    #: ``import módulo``).
    imports: dict[str, set[str]] = field(default_factory=dict)
    #: Identificador o atributo → líneas donde aparece.
    usos: dict[str, list[int]] = field(default_factory=dict)


def ficheros_python(root: Path) -> list[str]:
    """Los ``.py`` versionados, o los del disco si no hay git."""
    try:
        salida = subprocess.run(
            ["git", "ls-files", "--", "*.py"],  # noqa: S607 -- git del PATH, argumentos fijos
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=30,
        ).stdout
        rutas = [linea for linea in salida.splitlines() if linea]
    except (OSError, subprocess.SubprocessError):
        rutas = [p.relative_to(root).as_posix() for p in root.rglob("*.py")]
    return sorted(r for r in rutas if not any(parte in _EXCLUIDOS for parte in r.split("/")))


def nombre_de_modulo(fichero: str) -> str:
    """``db/repositories/__init__.py`` → ``db.repositories``."""
    partes = fichero[: -len(".py")].split("/")
    if partes[-1] == "__init__":
        partes = partes[:-1]
    return ".".join(partes)


def _resolver_relativo(modulo: Modulo, nodo: ast.ImportFrom) -> str:
    """Nombre absoluto de un ``from .x import y``."""
    paquete = modulo.nombre.split(".")
    if not modulo.fichero.endswith("__init__.py"):
        paquete = paquete[:-1]
    base = paquete[: len(paquete) - (nodo.level - 1)] if nodo.level > 1 else paquete
    return ".".join([*base, nodo.module] if nodo.module else base)


def analizar(root: Path, fichero: str) -> Modulo | None:
    """Extrae definiciones, imports y usos de un fichero. ``None`` si no parsea."""
    try:
        fuente = (root / fichero).read_text(encoding="utf-8")
        arbol = ast.parse(fuente)
    except (OSError, SyntaxError, ValueError):
        return None
    doc = ast.get_docstring(arbol) or ""
    modulo = Modulo(
        fichero=fichero,
        nombre=nombre_de_modulo(fichero),
        lineas=fuente.count("\n") + 1,
        resumen=doc.strip().splitlines()[0] if doc.strip() else "",
    )
    for nodo in arbol.body:
        if isinstance(nodo, ast.FunctionDef | ast.AsyncFunctionDef):
            modulo.definiciones.append(Definicion(nodo.name, "función", fichero, nodo.lineno))
        elif isinstance(nodo, ast.ClassDef):
            modulo.definiciones.append(Definicion(nodo.name, "clase", fichero, nodo.lineno))
            for miembro in nodo.body:
                if isinstance(miembro, ast.FunctionDef | ast.AsyncFunctionDef):
                    modulo.definiciones.append(
                        Definicion(f"{nodo.name}.{miembro.name}", "método", fichero, miembro.lineno)
                    )
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                modulo.imports.setdefault(alias.name, set())
        elif isinstance(nodo, ast.ImportFrom):
            origen = _resolver_relativo(modulo, nodo) if nodo.level else (nodo.module or "")
            if origen:
                modulo.imports.setdefault(origen, set()).update(a.name for a in nodo.names)
        elif isinstance(nodo, ast.Name):
            modulo.usos.setdefault(nodo.id, []).append(nodo.lineno)
        elif isinstance(nodo, ast.Attribute):
            modulo.usos.setdefault(nodo.attr, []).append(nodo.lineno)
    return modulo


def indexar(root: Path) -> dict[str, Modulo]:
    """Todos los módulos del repo, por nombre con puntos."""
    indice: dict[str, Modulo] = {}
    for fichero in ficheros_python(root):
        modulo = analizar(root, fichero)
        if modulo is not None:
            indice[modulo.nombre] = modulo
    return indice


def _normalizar_modulo(texto: str) -> str:
    """Acepta ``db/upsert.py``, ``db/upsert`` o ``db.upsert``."""
    limpio = texto.strip().replace("\\", "/").removeprefix("./")
    if limpio.endswith(".py") or "/" in limpio:
        return nombre_de_modulo(limpio if limpio.endswith(".py") else limpio.rstrip("/") + ".py")
    return limpio


def importa_a(modulo: Modulo, objetivo: str) -> bool:
    """¿``modulo`` importa ``objetivo``, un submódulo suyo, o lo trae por nombre?"""
    prefijo = objetivo + "."
    padre, _, hoja = objetivo.rpartition(".")
    for origen, nombres in modulo.imports.items():
        if origen == objetivo or origen.startswith(prefijo):
            return True
        if padre and origen == padre and hoja in nombres:
            return True
    return False


def importadores(indice: dict[str, Modulo], objetivo: str) -> list[Modulo]:
    return sorted(
        (m for m in indice.values() if m.nombre != objetivo and importa_a(m, objetivo)),
        key=lambda m: m.fichero,
    )


def definiciones_de(indice: dict[str, Modulo], nombre: str) -> list[Definicion]:
    """Definiciones cuyo nombre, o cuyo método, coincide con ``nombre``."""
    encontradas = [
        d
        for m in indice.values()
        for d in m.definiciones
        if d.nombre == nombre or d.nombre.rpartition(".")[2] == nombre
    ]
    return sorted(encontradas, key=lambda d: (d.fichero, d.linea))


def usos_de(indice: dict[str, Modulo], definicion: Definicion) -> list[tuple[str, list[int]]]:
    """Ficheros que importan el módulo de la definición y nombran el símbolo."""
    origen = nombre_de_modulo(definicion.fichero)
    hoja = definicion.nombre.rpartition(".")[2]
    resultado = []
    for modulo in importadores(indice, origen):
        lineas = sorted(set(modulo.usos.get(hoja, [])))
        if lineas:
            resultado.append((modulo.fichero, lineas))
    return resultado


def _es_test(fichero: str) -> bool:
    return fichero.startswith("tests/")


def _recortar(elementos: list[str], maximo: int) -> list[str]:
    if len(elementos) <= maximo:
        return elementos
    return [*elementos[:maximo], f"… y {len(elementos) - maximo} más (--max para verlos)"]


def cmd_simbolo(indice: dict[str, Modulo], nombre: str, maximo: int) -> list[str]:
    definiciones = definiciones_de(indice, nombre)
    if not definiciones:
        return [f"Sin definición de `{nombre}` (clase, función o método) en el código Python."]
    salida: list[str] = []
    for definicion in definiciones:
        salida.append(
            f"{definicion.tipo} {definicion.nombre}  {definicion.fichero}:{definicion.linea}"
        )
        usos = usos_de(indice, definicion)
        produccion = [f"  {f}:{','.join(map(str, ls[:6]))}" for f, ls in usos if not _es_test(f)]
        tests = [f"  {f}:{','.join(map(str, ls[:6]))}" for f, ls in usos if _es_test(f)]
        salida.append(f" usos en producción ({len(produccion)}):")
        salida.extend(_recortar(produccion, maximo))
        salida.append(f" usos en tests ({len(tests)}):")
        salida.extend(_recortar(tests, maximo))
    return salida


def cmd_importadores(indice: dict[str, Modulo], texto: str, maximo: int) -> list[str]:
    objetivo = _normalizar_modulo(texto)
    conocido = objetivo in indice or any(n.startswith(objetivo + ".") for n in indice)
    if not conocido:
        return [f"`{objetivo}` no es un módulo ni un paquete del repo."]
    quienes = importadores(indice, objetivo)
    produccion = [f"  {m.fichero}" for m in quienes if not _es_test(m.fichero)]
    tests = [f"  {m.fichero}" for m in quienes if _es_test(m.fichero)]
    return [
        f"{objetivo}: lo importan {len(produccion)} módulos de producción y {len(tests)} de tests",
        " producción:",
        *_recortar(produccion, maximo),
        " tests:",
        *_recortar(tests, maximo),
    ]


def cmd_paquete(indice: dict[str, Modulo], texto: str, maximo: int) -> list[str]:
    paquete = _normalizar_modulo(texto.rstrip("/") + "/__init__.py")
    modulos = sorted(
        (m for n, m in indice.items() if n == paquete or n.startswith(paquete + ".")),
        key=lambda m: m.fichero,
    )
    if not modulos:
        return [f"`{paquete}` no es un paquete del repo."]
    salida = [f"{paquete}: {len(modulos)} módulos, {sum(m.lineas for m in modulos)} líneas"]
    for modulo in modulos:
        publicas = [
            d.nombre
            for d in modulo.definiciones
            if d.tipo != "método" and not d.nombre.startswith("_")
        ]
        salida.append(f"{modulo.fichero}  ({modulo.lineas} líneas)  {modulo.resumen[:100]}")
        if publicas:
            salida.append("  " + ", ".join(_recortar(publicas, maximo)))
    return salida


def cmd_fichero(indice: dict[str, Modulo], texto: str, maximo: int) -> list[str]:
    nombre = _normalizar_modulo(texto)
    modulo = indice.get(nombre)
    if modulo is None:
        return [f"`{texto}` no es un fichero Python del repo."]
    raices = {n.split(".")[0] for n in indice}
    propios = sorted(o for o in modulo.imports if o.split(".")[0] in raices)
    salida = [f"{modulo.fichero}  ({modulo.lineas} líneas)  {modulo.resumen[:100]}"]
    salida.append(f" importa del repo ({len(propios)}):")
    salida.extend(_recortar([f"  {o}" for o in propios], maximo))
    salida.append(f" define ({len(modulo.definiciones)}):")
    salida.extend(
        _recortar([f"  {d.linea:>5}  {d.tipo} {d.nombre}" for d in modulo.definiciones], maximo)
    )
    return salida


_COMANDOS = {
    "simbolo": cmd_simbolo,
    "importadores": cmd_importadores,
    "paquete": cmd_paquete,
    "fichero": cmd_fichero,
}


def main(argv: list[str] | None = None, root: Path = _ROOT) -> int:
    parser = argparse.ArgumentParser(
        description="Mapa del código Python desde el AST (fallback sin el CLI graphify)."
    )
    parser.add_argument("comando", choices=sorted(_COMANDOS))
    parser.add_argument("objetivo", help="Nombre de símbolo, módulo con puntos o ruta")
    parser.add_argument("--max", type=int, default=40, help="Líneas por lista (40)")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    indice = indexar(root)
    print("\n".join(_COMANDOS[args.comando](indice, args.objetivo, args.max)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
