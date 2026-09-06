"""Las rutas de fichero que la documentación cita tienen que existir (C9.2).

`scripts/check_agent_docs.py::check_paths` ya hace esto para los ficheros de
*instrucciones* (AGENTS.md, el playbook, los rules de agentes). Lo que no cubría
es la documentación de arquitectura y contrato que un humano lee para decidir
dónde tocar: el README citaba `db/migrations.py`, que no existe desde la
consolidación Alembic, y `docs/api-design.md` citaba tres rutas HTTP que nunca
se implementaron.

El coste de un doc que miente no es cosmético: alguien abre el fichero que el
README nombra, no lo encuentra, y o bien lo crea otra vez o bien deja de fiarse
del documento entero.

Este test cubre dos cosas distintas:

1. **Rutas de fichero** citadas entre backticks o en enlaces Markdown.
2. **Rutas HTTP** citadas en `docs/api-design.md`, contra las rutas reales de
   la app — el defecto que motivó el ítem.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Documentos que un humano lee para orientarse. No son ficheros de instrucciones
# de agente (esos ya los cubre check_agent_docs), y por eso hasta hoy nadie los
# verificaba.
DOCS_VERIFICADOS = (
    "README.md",
    "docs/api-design.md",
    "docs/AGENT_PLAYBOOK.md",
    "docs/c4-architecture.md",
)

# Prefijos de artefactos que el código *produce* en tiempo de ejecución. Un doc
# que dice «el modelo se guarda en `data/models/...`» describe una salida, no
# afirma que el fichero esté commiteado; exigir que exista convertiría el test
# en ruido.
PREFIJOS_ARTEFACTO = ("data/", "coverage/", "htmlcov/", "dist/", "build/")

BACKTICK = re.compile(r"`([^`\n]+)`")
LINK_TARGET = re.compile(r"\]\(([^)\s]+)\)")

# Rutas que se citan como ejemplo o pertenecen a un entorno, no al árbol.
PATH_ALLOWLIST = frozenset(
    {
        "graphify-out/graph.json",
        "graphify-out/GRAPH_REPORT.md",
        "graphify-out/wiki/",
        "graphify-out/wiki/index.md",
        "graphify-out/.graph_stale",
    }
)

# Prefijos de rutas HTTP externas al contrato propio.
_HTTP_IGNORAR = ("/docs", "/redoc", "/openapi.json", "/metrics")


def _parece_ruta_de_fichero(token: str) -> bool:
    """Mismo criterio que `check_agent_docs.looks_like_path`, para no divergir."""
    if any(c in token for c in "*?{}<>$ |"):
        return False
    if token.startswith(("http", "mailto:", "#", "/")):
        return False
    if token.startswith("node_modules/") or "/node_modules/" in token:
        return False
    if "/" not in token.rstrip("/"):
        return False
    return bool(re.search(r"\.[a-z]{1,5}$", token) or token.endswith("/"))


@pytest.mark.parametrize("rel", DOCS_VERIFICADOS)
def test_rutas_de_fichero_citadas_existen(rel: str) -> None:
    doc = ROOT / rel
    assert doc.exists(), f"{rel} no existe"
    texto = doc.read_text(encoding="utf-8")

    faltantes: list[str] = []
    for token in sorted(set(BACKTICK.findall(texto))):
        token = token.strip().rstrip(",.;:")
        if not _parece_ruta_de_fichero(token) or token in PATH_ALLOWLIST:
            continue
        if token.startswith(PREFIJOS_ARTEFACTO):
            continue
        if not (ROOT / token).exists():
            faltantes.append(token)

    assert not faltantes, f"{rel} cita rutas de fichero que no existen: {faltantes}"


@pytest.mark.parametrize("rel", DOCS_VERIFICADOS)
def test_enlaces_markdown_resuelven(rel: str) -> None:
    doc = ROOT / rel
    base = doc.parent
    texto = doc.read_text(encoding="utf-8")

    rotos: list[str] = []
    for target in sorted(set(LINK_TARGET.findall(texto))):
        target = target.split("#")[0]
        if not target or target.startswith(("http", "mailto:")) or "*" in target:
            continue
        if not (base / target).exists():
            rotos.append(target)

    assert not rotos, f"{rel} tiene enlaces rotos: {rotos}"


def _rutas_reales_de_la_api() -> set[str]:
    from api.app import app

    rutas: set[str] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if isinstance(path, str) and path.startswith("/api/v1"):
            # Se normaliza el nombre del parámetro: el doc puede escribir
            # `{id}` donde el código escribe `{webhook_id}`, y eso no es una
            # mentira sobre la existencia de la ruta.
            rutas.add(re.sub(r"\{[^}]+\}", "{}", path[len("/api/v1") :]))
    return rutas


def test_api_design_no_cita_rutas_http_inexistentes() -> None:
    """`docs/api-design.md` citaba `/exports/{job_id}`, `/webhooks/{id}/test` y
    `/models/{name}/rollback`. Ninguna existió nunca."""
    reales = _rutas_reales_de_la_api()
    texto = (ROOT / "docs" / "api-design.md").read_text(encoding="utf-8")

    inexistentes: list[str] = []
    for token in sorted(set(BACKTICK.findall(texto))):
        token = token.strip().rstrip(",.;:")
        if not token.startswith("/") or token.startswith(_HTTP_IGNORAR):
            continue
        if "." in token.split("/")[-1] and not token.endswith((".ics", ".xml")):
            continue  # `/ruta.py`, no una ruta HTTP
        normalizada = re.sub(r"\{[^}]+\}", "{}", token)
        if normalizada.rstrip("/") in {r.rstrip("/") for r in reales}:
            continue
        # Prefijo de familia (`/analytics`) citado sin operación concreta.
        if any(r.startswith(normalizada.rstrip("/") + "/") for r in reales):
            continue
        inexistentes.append(token)

    assert not inexistentes, (
        "docs/api-design.md cita rutas HTTP que la API no expone: " f"{inexistentes}"
    )
