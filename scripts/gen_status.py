#!/usr/bin/env python3
"""Genera ``docs/STATUS.md`` a partir del código.

Regla que este script implementa: **si un hecho se puede calcular, no se
escribe a mano**. El backlog y los documentos de estado del proyecto derivaban
de la realidad —el ítem "cablear TED" siguió abierto semanas después de que
`b123828` lo integrase, y el propio backlog llegó a contener una entrada cuyo
único fin era corregir otra entrada anterior—. Todo lo que aparece aquí se
deriva del árbol de código en el momento de ejecutarlo, así que no puede
mentir.

La excepción es la línea «Último descenso» de cada ratchet: la tendencia no
está en el árbol, así que se lee del ``docs/STATUS.md`` que se va a
sobrescribir (ver ``_tendencia``).

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


def _user_key_ratchet() -> tuple[int, int]:
    """``(ficheros que usan user_key hoy, tamaño de la lista congelada)``.

    D18 fase 1: la identidad interna se deriva del correo y se está retirando.
    El número vive aquí y no en AGENTS.md porque es calculable, y porque es el
    único indicador de si T4 avanza: mientras no llegue a cero, cambiar de
    correo sigue costando los datos de una persona.
    """
    sys.path.insert(0, str(_ROOT / "scripts"))
    import check_user_key_ratchet

    return len(check_user_key_ratchet._ficheros_con_user_key()), len(
        check_user_key_ratchet.CONGELADOS
    )


def _capas_ratchet() -> tuple[list[str], tuple[str, ...]]:
    """``(imports contra el orden de capas, ese orden)`` según ``scripts/check_layers.py``."""
    sys.path.insert(0, str(_ROOT / "scripts"))
    import check_layers

    return check_layers.violaciones(), check_layers.CAPAS


_DESCENSO = re.compile(r"^Último descenso: .*$", re.MULTILINE)


def _tendencia(previo: str, titulo: str, valor: int, hoy: str) -> str:
    """Línea «Último descenso» de un ratchet, leída del STATUS.md anterior.

    Si el valor de la sección ``titulo`` bajó respecto a ``previo``, el descenso
    es de ``hoy``; si no, se conserva la línea que ya había, así que ``--check``
    sigue siendo determinista mientras el valor no cambie.
    """
    inicio = previo.find(titulo)
    seccion = previo[inicio:].split("\n## ", 1)[0] if inicio != -1 else ""
    antes = re.search(r"^\*\*(\d+) ", seccion, re.MULTILINE)
    if antes and valor < int(antes.group(1)):
        return f"Último descenso: {hoy} (desde {antes.group(1)})"
    linea = _DESCENSO.search(seccion)
    return linea.group(0) if linea else "Último descenso: sin registrar"


def _superficie_ratchet() -> tuple[int, int]:
    """``(líneas de la base congelada, operaciones añadidas con motivo)``."""
    sys.path.insert(0, str(_ROOT / "scripts"))
    import check_api_surface

    return len(check_api_surface.leer_base()), len(check_api_surface.NUEVAS)


def _jobs_table() -> tuple[list[dict], list[str]]:
    sys.path.insert(0, str(_ROOT / "scripts"))
    import check_job_parity

    return check_job_parity.check()


def _endpoints() -> list[tuple[str, str]]:
    """Operaciones que expone la API, como ``(MÉTODO, plantilla)``.

    Las calcula ``api.rutas.operaciones``: ancla en ``app.openapi()`` y falla
    si el recorrido de rutas deja de ver alguna operación del esquema, que es
    como se rompió esto con fastapi 0.141 (de 154 endpoints a 7 sin avisar).
    El recorrido aporta las rutas fuera del esquema y el conversor ``:path``.
    """
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from api.app import app
    from api.rutas import operaciones

    return operaciones(app)


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
    hoy = datetime.now(UTC).date().isoformat()
    previo = _OUT.read_text(encoding="utf-8") if _OUT.exists() else ""
    tid251 = "## Ratchet TID251 — acceso directo a BD fuera de repositories"
    user_key = "## Ratchet `user_key` — identidad derivada del correo (D18, fase 1)"
    capas_titulo = "## Ratchet de capas — imports contra el orden de paquetes"

    lines: list[str] = [
        "---",
        "tags: [status, generado]",
        "---",
        "",
        "# Estado del proyecto (derivado del código)",
        "",
        _MARKER,
        "",
        f"Generado: {hoy}",
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
        tid251,
        "",
        f"**{len(whitelist)} archivos** en whitelist (solo puede decrecer).",
        "",
        _tendencia(previo, tid251, len(whitelist), hoy),
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
    usan_user_key, congelados = _user_key_ratchet()
    capas, orden_capas = _capas_ratchet()
    base_superficie, nuevas_superficie = _superficie_ratchet()
    lines += [
        "",
        user_key,
        "",
        f"**{usan_user_key} ficheros** de producción usan `user_key` "
        f"(lista congelada: {congelados}; solo puede decrecer).",
        "",
        _tendencia(previo, user_key, usan_user_key, hoy),
        "",
        "`scripts/check_user_key_ratchet.py` falla ante un fichero nuevo que la "
        "use. Llega a cero con T4, que migra a `user_id` con columna doble y "
        "lectura dual; hasta entonces cambiar de correo pierde los datos que "
        "cuelgan de esa clave. No cuenta `tests/` ni `db/alembic/versions/`.",
        "",
        capas_titulo,
        "",
        f"**{len(capas)} imports** van de una capa a otra superior (lista congelada; "
        "solo puede decrecer).",
        "",
        _tendencia(previo, capas_titulo, len(capas), hoy),
        "",
        "`scripts/check_layers.py` falla ante uno nuevo, también si está dentro de "
        f"una función. Orden, de abajo arriba: `{' < '.join(orden_capas)}`.",
        "",
        *[f"- `{v}`" for v in capas],
        "",
        "## Motor de la suite de tests (ADR-018)",
        "",
        _test_engine_status(),
        "",
        "## Superficie de la API",
        "",
        f"**{len(endpoints)} endpoints** expuestos.",
        "",
        f"Línea base congelada: **{base_superficie}** (solo puede decrecer). "
        f"Añadidos después, cada uno con su motivo: **{nuevas_superficie}** "
        "(`scripts/check_api_surface.py`).",
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
