#!/usr/bin/env python3
"""Ratchet de capas: un paquete no importa de otro que está por encima.

ADR-022 fijó **dónde vive el SQL** y TID251 lo vigila, pero nada vigilaba la
dirección de los imports entre paquetes. El resultado, medido el 2026-10-10:
el worker importaba un módulo de rutas de la API, ``db/`` sacaba su política de
reintentos de ``services/``, y ``shared/`` abría repositorios. Casi todos esos
imports están dentro de una función, que es como se esconde un ciclo: el módulo
carga, y la dependencia invertida no aparece hasta que alguien intenta mover o
empaquetar una de las dos mitades por separado.

El orden, de abajo arriba (ver ``CAPAS``)::

    config < observability < shared < llm < db < services < scraper < scheduler < api

Un módulo puede importar de su paquete y de cualquiera **por debajo**. Importar
de uno por encima es una violación. Además hay aristas prohibidas aunque el
orden las permita (``PROHIBIDAS``): la API no importa del paquete de ingesta.

Qué se cuenta
-------------

* Todo ``import x.y`` y ``from x.y import z`` absoluto, **también los que están
  dentro de una función o de un bloque ``TYPE_CHECKING``**. Un import diferido
  no rompe el arranque, pero es la misma dependencia.
* Solo código de producción de los paquetes de ``CAPAS``. ``scripts/`` y
  ``tests/`` son puntos de entrada: componen lo que haga falta.
* ``db/alembic/versions/`` queda fuera: las migraciones son históricas y
  append-only, no se pueden arreglar.

Cómo funciona el ratchet
------------------------

``CONGELADAS`` lista las violaciones que existían al escribir el gate, una por
``(fichero, módulo importado)``. Una violación nueva falla. Una entrada que ya
no corresponde a un import real también falla: la lista solo puede encoger, y
tiene que decir la verdad sobre el tamaño de la deuda.

Uso::

    python scripts/check_layers.py           # falla ante una violación nueva o un fósil
    python scripts/check_layers.py --list    # imprime las violaciones de hoy
    python scripts/check_layers.py --count   # solo el número (make status)
"""

from __future__ import annotations

import argparse
import ast
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

#: Paquetes de producción, de la capa más baja a la más alta. La posición es
#: el contrato: mover un paquete de sitio es una decisión de arquitectura.
CAPAS: tuple[str, ...] = (
    "config",
    "observability",
    "shared",
    "llm",
    "db",
    "services",
    "scraper",
    "scheduler",
    "api",
)

#: Aristas prohibidas aunque el orden las permita: ``(quien importa, de quién)``.
#: ``api → scraper``: servir una petición no depende del paquete de ingesta. Es
#: lo que llevó los clasificadores de ``scraper/`` a ``services/ml/``.
PROHIBIDAS: frozenset[tuple[str, str]] = frozenset({("api", "scraper")})

#: Directorios excluidos del escaneo (ver el docstring del módulo).
_EXCLUIDOS = ("db/alembic/versions/",)

# ── RATCHET: imports que hoy van contra el orden de capas ───────────────────
# Medido con este mismo script el 2026-10-10 sobre la cabeza del repo.
# **Añadir líneas está prohibido.** Para quitar una: mové la pieza compartida a
# la capa de abajo (o invertí la dependencia pasando el colaborador como
# argumento) y borrá su entrada.
#
# Formato: ``"fichero -> módulo importado"``.
CONGELADAS: frozenset[str] = frozenset(
    {
        "api/routes/publico.py -> scraper.connectors",
        "config/secrets.py -> observability.logging",
        "config/settings.py -> shared.password_policy",
        "config/settings.py -> shared.scoring_weights",
        "db/access_grants.py -> services.access_grants",
        "db/repositories/go_no_go.py -> services.go_no_go_template",
        "db/repositories/licitaciones.py -> services.investigador.search_engine",
        "db/webhooks.py -> services.webhook_retry",
        "observability/alerts.py -> db.database",
        "observability/alerts.py -> db.job_locks",
        "observability/alerts.py -> services.extraction_runs",
        "observability/mailer.py -> shared.outbound_http",
        "observability/metrics.py -> services.extraction_runs",
        "observability/ops_events.py -> db.connection",
        "observability/runtime_metrics.py -> db.connection",
        "services/ml/sap_classifier.py -> scraper.seed_negatives",
        "services/rag/fact_sheet.py -> scraper.document_fetcher",
        "services/source_health.py -> scraper.connectors",
        "services/tech_signal.py -> scraper.filters",
        "shared/cache_signal.py -> db.events",
        "shared/jobs.py -> db.repositories.jobs",
        "shared/model_artifacts.py -> db.model_registry",
    }
)


def _ficheros() -> list[str]:
    """Ficheros ``.py`` versionados de los paquetes de ``CAPAS``.

    Se pregunta a git (y no a un ``Path.rglob``) por la misma razón que el resto
    de gates del repo: lo que no está versionado no es código del proyecto.
    """
    git = shutil.which("git")
    if git is None:  # pragma: no cover - CI y pre-commit siempre lo tienen
        raise RuntimeError("Este gate necesita git en el PATH para enumerar el repo.")
    # argv fijo, sin shell y sin ninguna entrada del usuario. `--others
    # --exclude-standard` suma los ficheros nuevos aún sin `git add`: un módulo
    # recién creado tiene que pasar el gate antes de su primer commit, no después.
    salida = subprocess.run(
        [git, "ls-files", "--cached", "--others", "--exclude-standard", "--", "*.py"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    rutas: list[str] = []
    for linea in salida.splitlines():
        ruta = linea.strip()
        if not ruta or ruta.startswith(_EXCLUIDOS):
            continue
        if ruta.split("/", 1)[0] in CAPAS and (_ROOT / ruta).exists():
            rutas.append(ruta)
    return sorted(set(rutas))


def _modulos_importados(fuente: str) -> set[str]:
    """Módulos absolutos que importa un fichero, a cualquier profundidad."""
    modulos: set[str] = set()
    for nodo in ast.walk(ast.parse(fuente)):
        if isinstance(nodo, ast.Import):
            modulos.update(alias.name for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
            modulos.add(nodo.module)
    return modulos


def es_violacion(origen: str, destino: str) -> bool:
    """¿Puede el paquete ``origen`` importar del paquete ``destino``?"""
    if origen == destino or origen not in CAPAS or destino not in CAPAS:
        return False
    if (origen, destino) in PROHIBIDAS:
        return True
    return CAPAS.index(destino) > CAPAS.index(origen)


def violaciones() -> list[str]:
    """Violaciones del árbol de hoy, como ``"fichero -> módulo"``, ordenadas."""
    encontradas: set[str] = set()
    for ruta in _ficheros():
        origen = ruta.split("/", 1)[0]
        try:
            fuente = (_ROOT / ruta).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for modulo in _modulos_importados(fuente):
            if es_violacion(origen, modulo.split(".", 1)[0]):
                encontradas.add(f"{ruta} -> {modulo}")
    return sorted(encontradas)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="imprime las violaciones actuales")
    parser.add_argument("--count", action="store_true", help="imprime solo el conteo")
    args = parser.parse_args(argv)

    actuales = violaciones()

    if args.count:
        print(len(actuales))
        return 0
    if args.list:
        print("\n".join(actuales))
        return 0

    nuevas = sorted(set(actuales) - CONGELADAS)
    fosiles = sorted(CONGELADAS - set(actuales))

    if nuevas:
        print(
            f"{len(nuevas)} import(s) NUEVO(s) van contra el orden de capas:",
            file=sys.stderr,
        )
        for entrada in nuevas:
            print(f"  - {entrada}", file=sys.stderr)
        print(
            "\nOrden (de abajo arriba): " + " < ".join(CAPAS) + ".\n"
            "Un paquete importa de sí mismo y de los que tiene por debajo. Si dos "
            "capas necesitan la misma pieza, la pieza baja a la capa inferior; si "
            "la de abajo necesita un comportamiento de la de arriba, lo recibe "
            "como argumento. Un import dentro de una función cuenta igual.",
            file=sys.stderr,
        )
    if fosiles:
        print(
            f"\n{len(fosiles)} entrada(s) de la lista ya no corresponden a un import: "
            "bórralas de CONGELADAS, el ratchet solo puede encoger.",
            file=sys.stderr,
        )
        for entrada in fosiles:
            print(f"  - {entrada}", file=sys.stderr)

    if nuevas or fosiles:
        return 1

    print(f"Ratchet de capas OK: {len(actuales)} imports congelados, ninguno nuevo.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
