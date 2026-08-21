#!/usr/bin/env python3
"""Genera ``docs/STATUS.md`` a partir del código.

Regla que este script implementa: **si un hecho se puede calcular, no se
escribe a mano**. El backlog y los documentos de estado del proyecto derivaban
de la realidad —el ítem "cablear TED" siguió abierto semanas después de que
`b123828` lo integrase, y el propio backlog llegó a contener una entrada cuyo
único fin era corregir otra entrada anterior—. Todo lo que aparece aquí se
deriva del árbol de código en el momento de ejecutarlo, así que no puede
mentir.

Uso::

    python scripts/gen_status.py            # escribe docs/STATUS.md
    python scripts/gen_status.py --check    # falla si el fichero está desfasado
"""

from __future__ import annotations

import difflib
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_OUT = _ROOT / "docs" / "STATUS.md"

_MARKER = "<!-- generado por scripts/gen_status.py — no editar a mano -->"


def _tid251_whitelist() -> list[str]:
    """Archivos con acceso directo a BD todavía permitidos (ratchet decreciente)."""
    text = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"# ── RATCHET TID251.*?# ── fin RATCHET TID251 ──", text, re.DOTALL)
    if not block:
        return []
    files = re.findall(r'^"([^"]+)"\s*=\s*\[[^\]]*"TID251"', block.group(0), re.MULTILINE)
    # db/** y tests/* son legítimos por diseño, no deuda.
    return sorted(f for f in files if not f.startswith(("db/", "tests/")))


def _stale_whitelist_entries(whitelist: list[str]) -> list[str]:
    """Entradas del ratchet que apuntan a archivos que ya no existen.

    Una whitelist que solo puede decrecer también acumula fósiles: al borrar
    ``scheduler/jobs/wal_checkpoint.py`` su línea quedó ahí, inflando el
    conteo del ratchet con deuda que en realidad ya no existe.
    """
    return [f for f in whitelist if "*" not in f and not (_ROOT / f).exists()]


def _jobs_table() -> tuple[list[dict], list[str]]:
    sys.path.insert(0, str(_ROOT / "scripts"))
    import check_job_parity

    return check_job_parity.check()


def _rutas_efectivas(routes: list[Any]) -> list[Any]:
    """Aplana los routers incluidos a rutas que llevan su propio ``path``.

    Con el fastapi que fija el pin (``>=0.110,<0.137``) ``include_router``
    deja las ``APIRoute`` ya aplanadas en ``app.routes`` y esto es la
    identidad. Desde 0.141 los routers incluidos pasan a ser objetos
    ``_IncludedRouter`` opacos, sin ``.path`` ni ``.methods``: el bucle de
    ``_endpoints`` los descartaría por el ``continue`` y STATUS.md pasaría de
    154 endpoints a 7 **sin fallar**, que es el modo de fallo peor de los dos
    (el razonamiento del techo está en ``requirements.in``, PR #187). Esos
    routers sí exponen ``effective_route_contexts()``, que devuelve contextos
    cuya ruta resuelta ya viene con el prefijo aplicado.

    Es el mismo aplanado que hace ``prometheus_fastapi_instrumentator.routing``
    (``_effective_routes``) —dependencia nuestra que ya absorbió esta subida—,
    copiado a propósito en vez de importado: es API privada suya.
    """
    efectivas: list[Any] = []
    for route in routes:
        contextos = getattr(route, "effective_route_contexts", None)
        if not callable(contextos):
            efectivas.append(route)
            continue
        for contexto in contextos():
            # Las rutas planas de Starlette llevan la ruta ya prefijada en
            # `starlette_route`; las de FastAPI lo dejan sin fijar y es el
            # propio contexto el que expone `.path`.
            starlette_route = getattr(contexto, "starlette_route", None)
            efectivas.append(contexto if starlette_route is None else starlette_route)
    return efectivas


def _endpoints() -> list[tuple[str, str]]:
    """Rutas expuestas por la API, leídas del router de FastAPI."""
    from api.app import app

    out: list[tuple[str, str]] = []
    for route in _rutas_efectivas(app.routes):
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue
        for method in sorted(methods - {"HEAD", "OPTIONS"}):
            out.append((method, path))
    return sorted(out, key=lambda r: (r[1], r[0]))


def _test_engine_status() -> str:
    """Indica si CI ejercita la suite contra el motor de producción (ADR-018)."""
    ci = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    if "TEST_DATABASE_URL" not in ci:
        return "❌ la suite solo corre sobre SQLite; producción es Postgres"
    # El job existe; ¿es bloqueante?
    block = ci.split("test-postgres:", 1)[-1]
    if "continue-on-error: true" in block.split("Security audit")[0]:
        return "⚠️ job `test-postgres` presente pero **no bloqueante** (ADR-018)"
    return "✅ la suite corre contra Postgres y el job es bloqueante"


def render() -> str:
    jobs, problems = _jobs_table()
    whitelist = _tid251_whitelist()
    endpoints = _endpoints()

    lines: list[str] = [
        "---",
        "tags: [status, generado]",
        "---",
        "",
        "# Estado del proyecto (derivado del código)",
        "",
        _MARKER,
        "",
        f"Generado: {datetime.now(UTC).date().isoformat()}",
        "",
        "## Paridad de planos de orquestación (ADR-012)",
        "",
        "| Job | Plano | Cubierto por |",
        "|---|---|---|",
    ]
    lines += [f"| `{j['job']}` | {j['plane']} | {j['cubierto_por']} |" for j in jobs]
    lines += [
        "",
        (
            f"**{len(problems)} job(s) sin plano de ejecución.**"
            if problems
            else f"**{len(jobs)} jobs, todos con plano verificado.**"
        ),
        "",
        "## Ratchet TID251 — acceso directo a BD fuera de repositories",
        "",
        f"**{len(whitelist)} archivos** en whitelist (solo puede decrecer).",
        "",
    ]
    stale = _stale_whitelist_entries(whitelist)
    if stale:
        lines += [
            "⚠️ Entradas que apuntan a archivos inexistentes — bórralas de "
            "`pyproject.toml`, inflan el conteo con deuda que ya no existe:",
            "",
        ]
        lines += [f"- ~~`{f}`~~" for f in stale]
        lines += [""]
    lines += [f"- `{f}`" for f in whitelist if f not in stale]
    lines += [
        "",
        "## Motor de la suite de tests (ADR-018)",
        "",
        _test_engine_status(),
        "",
        "## Superficie de la API",
        "",
        f"**{len(endpoints)} endpoints** expuestos.",
        "",
        "<details><summary>Ver listado</summary>",
        "",
        "| Método | Ruta |",
        "|---|---|",
    ]
    lines += [f"| {m} | `{p}` |" for m, p in endpoints]
    lines += ["", "</details>", ""]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    content = render()

    if "--check" in argv:
        if not _OUT.exists():
            print(f"{_OUT} no existe. Ejecuta: make status", file=sys.stderr)
            return 1
        current = _OUT.read_text(encoding="utf-8")

        def _strip_date(text: str) -> str:
            """La fecha cambia cada día; se compara todo lo demás."""
            return re.sub(r"^Generado: .*$", "", text, flags=re.MULTILINE)

        if _strip_date(current) != _strip_date(content):
            print(
                f"{_OUT.relative_to(_ROOT)} está desfasado respecto al código. "
                "Ejecuta: make status",
                file=sys.stderr,
            )
            diff = difflib.unified_diff(
                current.splitlines(),
                content.splitlines(),
                fromfile="docs/STATUS.md (commiteado)",
                tofile="docs/STATUS.md (derivado del código)",
                lineterm="",
            )
            print("\n".join(diff), file=sys.stderr)
            return 1
        print(f"{_OUT} sincronizado.")
        return 0

    _OUT.write_text(content, encoding="utf-8")
    print(f"Escrito {_OUT.relative_to(_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
