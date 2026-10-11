#!/usr/bin/env python3
"""Trazabilidad entre los casos de uso y los tests que los recorren.

``docs/casos-de-uso.md`` lista lo que una persona tiene que poder hacer con el
producto. Una lista así se queda vieja en cuanto nadie la comprueba, y un test
de una sola ruta no demuestra que un caso de uso funcione: demuestra que una
pieza responde. Este gate une las dos cosas.

Cómo funciona
-------------

* Cada caso es un encabezado ``### CU-NN — título`` del catálogo.
* Un test **cita** un caso escribiendo su identificador (``CU-07``) en su
  docstring, su título o un comentario dentro del test. Una mención antes del
  primer test del fichero cita el caso para el fichero entero.
* Un caso necesita al menos un **recorrido**: un test de escenario por la API
  (``tests/test_escenario_*.py``) o un E2E de navegador (``web/e2e/``). Los
  demás tests que lo citen se listan, pero no cuentan: fijan piezas, no el
  camino.
* ``SIN_RECORRIDO`` es la única excepción, con el motivo escrito. **No se le
  añaden entradas para salir del paso**: se añade el recorrido. Una entrada
  cuyo caso ya tiene recorrido falla, para que la lista solo encoja.
* Un identificador citado que no está en el catálogo falla: o es una errata o
  el caso se retiró y el test sigue diciendo que lo cubre.

La tabla «Trazabilidad» del catálogo se genera aquí. Editarla a mano no sirve:
el gate la compara con lo que saldría de los tests de hoy.

Uso::

    python scripts/check_casos_uso.py            # el gate (lo que corre CI)
    python scripts/check_casos_uso.py --write    # regenera la tabla del catálogo
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_CATALOGO = _ROOT / "docs" / "casos-de-uso.md"

_INICIO = "<!-- trazabilidad: generado por scripts/check_casos_uso.py — no editar a mano -->"
_FIN = "<!-- fin trazabilidad -->"

#: Un motivo más corto no puede decir qué impide el recorrido.
MOTIVO_MINIMO = 40

# ── Casos sin recorrido ─────────────────────────────────────────────────────
# Formato: ``"CU-NN": "qué impide recorrerlo de punta a punta hoy"``.
SIN_RECORRIDO: dict[str, str] = {}

_ID = re.compile(r"\bCU-\d{2}\b")
_CASO = re.compile(r"^### (CU-\d{2}) — (.+?)\s*$", re.MULTILINE)
_TEST_PY = re.compile(r"^\s*(?:async\s+)?def (test_\w+)\s*\(")
_TEST_TS = re.compile(r"^\s*(?:test|it)(?:\.\w+)*\(\s*[\"'`]")

#: El test de este gate cita identificadores inventados para mover una pieza
#: por caso; no cubre ningún caso de uso.
_EXCLUIDOS = {"tests/test_unit_ratchet_casos_uso.py"}

Nivel = str  # "escenario" | "e2e" | "otros"


@dataclass
class Cita:
    """Un fichero de tests que cita un caso, y cuántos de sus tests lo hacen."""

    ruta: str
    nivel: Nivel
    tests: int = 0
    fichero_entero: bool = False


@dataclass
class Estado:
    casos: dict[str, str]
    citas: dict[str, list[Cita]] = field(default_factory=dict)

    def recorridos(self, caso: str) -> list[Cita]:
        return [c for c in self.citas.get(caso, []) if c.nivel != "otros"]


def leer_casos(texto: str) -> tuple[dict[str, str], list[str]]:
    """``{id: título}`` del catálogo y los identificadores repetidos."""
    casos: dict[str, str] = {}
    repetidos: list[str] = []
    for identificador, titulo in _CASO.findall(texto):
        if identificador in casos:
            repetidos.append(identificador)
        casos[identificador] = titulo
    return casos, repetidos


def _nivel(ruta: str) -> Nivel:
    if ruta.startswith("tests/test_escenario_"):
        return "escenario"
    if ruta.startswith("web/e2e/"):
        return "e2e"
    return "otros"


def ficheros_de_test(raiz: Path) -> list[Path]:
    encontrados: list[Path] = []
    encontrados += sorted((raiz / "tests").glob("test_*.py"))
    e2e = raiz / "web" / "e2e"
    if e2e.is_dir():
        encontrados += sorted(e2e.rglob("*.ts"))
    fuente = raiz / "web" / "src"
    if fuente.is_dir():
        encontrados += sorted(
            p for patron in ("*.test.ts", "*.test.tsx") for p in fuente.rglob(patron)
        )
    return [p for p in encontrados if p.relative_to(raiz).as_posix() not in _EXCLUIDOS]


def citas_de(texto: str, ruta: str) -> dict[str, Cita]:
    """Casos que cita un fichero. Cuenta tests, no menciones."""
    declaracion = _TEST_PY if ruta.endswith(".py") else _TEST_TS
    citas: dict[str, Cita] = {}
    en_test = False
    vistos_en_este_test: set[str] = set()
    for linea in texto.splitlines():
        if declaracion.match(linea):
            en_test = True
            vistos_en_este_test = set()
        for identificador in _ID.findall(linea):
            cita = citas.setdefault(identificador, Cita(ruta=ruta, nivel=_nivel(ruta)))
            if not en_test:
                cita.fichero_entero = True
            elif identificador not in vistos_en_este_test:
                vistos_en_este_test.add(identificador)
                cita.tests += 1
    return citas


def calcular(raiz: Path | None = None, catalogo: Path | None = None) -> tuple[Estado, list[str]]:
    """Casos del catálogo y quién los cita. Llamada tal cual, sobre el repo."""
    raiz = raiz or _ROOT
    catalogo = catalogo or _CATALOGO
    casos, repetidos = leer_casos(catalogo.read_text(encoding="utf-8"))
    estado = Estado(casos=casos)
    for fichero in ficheros_de_test(raiz):
        ruta = fichero.relative_to(raiz).as_posix()
        for identificador, cita in citas_de(fichero.read_text(encoding="utf-8"), ruta).items():
            estado.citas.setdefault(identificador, []).append(cita)
    return estado, repetidos


def _celda(citas: list[Cita]) -> str:
    if not citas:
        return "—"
    partes = []
    for cita in sorted(citas, key=lambda c: c.ruta):
        nombre = cita.ruta.rsplit("/", 1)[1]
        cuantos = "" if cita.fichero_entero or cita.tests <= 1 else f" (x{cita.tests})"
        partes.append(f"[{nombre}](../{cita.ruta}){cuantos}")
    return "<br>".join(partes)


def tabla(estado: Estado) -> str:
    """La sección generada del catálogo, sin los marcadores."""
    lineas = [
        "| Caso | Recorrido por la API | E2E en el navegador | Otros tests que lo citan |",
        "|---|---|---|---|",
    ]
    for caso in sorted(estado.casos):
        citas = estado.citas.get(caso, [])
        por_nivel = {n: [c for c in citas if c.nivel == n] for n in ("escenario", "e2e", "otros")}
        lineas.append(
            f"| **{caso}** {estado.casos[caso]} | {_celda(por_nivel['escenario'])} "
            f"| {_celda(por_nivel['e2e'])} | {_celda(por_nivel['otros'])} |"
        )
    con_recorrido = sum(1 for caso in estado.casos if estado.recorridos(caso))
    lineas += [
        "",
        f"**{len(estado.casos)} casos**, {con_recorrido} con recorrido y "
        f"{len(estado.casos) - con_recorrido} sin él (ver `SIN_RECORRIDO` en "
        "`scripts/check_casos_uso.py`).",
    ]
    return "\n".join(lineas)


def con_tabla(texto: str, nueva: str) -> str | None:
    """El catálogo con la tabla sustituida, o ``None`` si faltan los marcadores."""
    if _INICIO not in texto or _FIN not in texto:
        return None
    antes, resto = texto.split(_INICIO, 1)
    _, despues = resto.split(_FIN, 1)
    return f"{antes}{_INICIO}\n\n{nueva}\n\n{_FIN}{despues}"


def problemas(estado: Estado, repetidos: list[str]) -> list[str]:
    errores: list[str] = []
    if not estado.casos:
        errores.append("El catálogo no declara ningún caso (`### CU-NN — título`).")
    for identificador in sorted(set(repetidos)):
        errores.append(f"{identificador} está declarado dos veces en el catálogo.")

    for identificador in sorted(set(estado.citas) - set(estado.casos)):
        donde = ", ".join(sorted(c.ruta for c in estado.citas[identificador]))
        errores.append(
            f"{identificador} se cita en {donde} pero no está en el catálogo: o es una "
            "errata o el caso se retiró y el test sigue diciendo que lo cubre."
        )

    for caso in sorted(estado.casos):
        tiene = bool(estado.recorridos(caso))
        if not tiene and caso not in SIN_RECORRIDO:
            errores.append(
                f"{caso} ({estado.casos[caso]}) no tiene ningún recorrido: hace falta un "
                "test de escenario (tests/test_escenario_*.py) o un E2E (web/e2e/) que lo "
                "cite. Un test de una sola ruta no cuenta."
            )
        if tiene and caso in SIN_RECORRIDO:
            errores.append(
                f"{caso} ya tiene recorrido: borrá su entrada de SIN_RECORRIDO, la lista "
                "solo puede encoger."
            )

    for caso, motivo in sorted(SIN_RECORRIDO.items()):
        if caso not in estado.casos:
            errores.append(f"SIN_RECORRIDO nombra {caso}, que no está en el catálogo.")
        if len(motivo.strip()) < MOTIVO_MINIMO:
            errores.append(
                f"El motivo de {caso} en SIN_RECORRIDO no dice qué impide recorrerlo "
                f"(menos de {MOTIVO_MINIMO} caracteres)."
            )
    return errores


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="regenera la tabla del catálogo")
    args = parser.parse_args(argv)

    estado, repetidos = calcular()
    texto = _CATALOGO.read_text(encoding="utf-8")
    esperado = con_tabla(texto, tabla(estado))

    if args.write:
        if esperado is None:
            print(f"Faltan los marcadores de la tabla en {_CATALOGO.name}.", file=sys.stderr)
            return 1
        _CATALOGO.write_text(esperado, encoding="utf-8", newline="\n")

    errores = problemas(estado, repetidos)
    if esperado is None:
        errores.append(f"Faltan los marcadores de la tabla generada en docs/{_CATALOGO.name}.")
    elif not args.write and esperado != texto:
        errores.append(
            f"La tabla de trazabilidad de docs/{_CATALOGO.name} está desfasada: "
            "regenerala con `make casos-uso`."
        )

    if errores:
        print(f"{len(errores)} problema(s) en los casos de uso:", file=sys.stderr)
        for error in errores:
            print(f"  - {error}", file=sys.stderr)
        return 1

    con_recorrido = sum(1 for caso in estado.casos if estado.recorridos(caso))
    print(
        f"Casos de uso OK: {len(estado.casos)} casos, {con_recorrido} con recorrido, "
        f"{len(SIN_RECORRIDO)} sin él con motivo."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
