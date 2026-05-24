#!/usr/bin/env python3
"""
agent_pick_item.py — Selecciona un ítem del backlog para que el agente trabaje.

Si no hay ítems elegibles, auto-descubre candidatos P3 analizando el codebase
y los agrega al backlog con marca `agent:auto-discovered`.

Criterios de elegibilidad:
  - Prioridad P2 o P3
  - Riesgo: bajo
  - Paths no incluyen path_denylist del coder
  - Sin marcas agent:skip ni human-only
  - No intentado en las últimas 7 noches (state en GitHub Actions cache)

Uso:
  python scripts/agent_pick_item.py          # elige ítem y lo imprime como JSON
  python scripts/agent_pick_item.py --list   # lista todos los elegibles
  python scripts/agent_pick_item.py --discover-only  # solo auto-descubre, no elige
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
BACKLOG_PATH = REPO_ROOT / "docs" / "IMPROVEMENT_BACKLOG.md"
STATE_FILE = REPO_ROOT / ".github" / "agent-state" / "attempted.json"

# Paths que el coder no puede tocar → ítems que los requieran son inelegibles
CODER_PATH_DENYLIST = [
    "db/alembic/",
    ".github/workflows/",
    ".env",
    "pyproject.toml",
    "requirements",
    ".secrets.baseline",
    ".gitleaks.toml",
    # tests/ está permitido para el test_engineer pero el pick no lo bloquea
]

# Marcas que hacen inelegible un ítem
SKIP_MARKS = ["agent:skip", "human-only", "human only", "requiere ok humano"]

# Días de cooldown: no reintentar un ítem hasta que pasen N días
COOLDOWN_DAYS = 7


# ---------------------------------------------------------------------------
# Parser del backlog
# ---------------------------------------------------------------------------


def parse_backlog(text: str) -> list[dict[str, object]]:
    """Parsea IMPROVEMENT_BACKLOG.md y retorna lista de ítems abiertos."""
    items: list[dict[str, object]] = []

    # Detectar sección de cerrados para no parsear ítems cerrados
    cerrados_match = re.search(r"^## Cerrados", text, re.MULTILINE)
    active_text = text[: cerrados_match.start()] if cerrados_match else text

    # Prioridad actual (se actualiza al encontrar headers P0-P3)
    current_priority = ""

    # Dividir por headers H3 (### Título del ítem)
    sections = re.split(r"^(#{1,3} .+)$", active_text, flags=re.MULTILINE)

    for i, section in enumerate(sections):
        # Detectar cabecera de prioridad (## P0, ## P1, etc.)
        p_match = re.match(r"^## (P[0-3])", section.strip())
        if p_match:
            current_priority = p_match.group(1)
            continue

        # Detectar ítem (### Título)
        item_match = re.match(r"^### (.+)$", section.strip())
        if not item_match:
            continue

        title = item_match.group(1).strip()

        # Saltar ítems tachados (~~Título~~)
        if title.startswith("~~") and title.endswith("~~"):
            continue

        # Contenido del ítem (siguiente sección)
        body = sections[i + 1] if i + 1 < len(sections) else ""

        # Extraer campos
        item: dict[str, object] = {
            "title": title,
            "priority": current_priority,
            "body": body,
        }

        # Riesgo
        risk_match = re.search(r"\*\*Riesgo[:\*]*\*?\*?\s*([^.\n]+)", body, re.IGNORECASE)
        if risk_match:
            risk_raw = risk_match.group(1).strip().lower()
            # Normalizar: tomar solo la primera palabra
            risk_word = risk_raw.split()[0] if risk_raw.split() else risk_raw
            item["risk"] = risk_word
        else:
            item["risk"] = "desconocido"

        # Files de partida
        files_match = re.search(r"\*\*Files de partida[:\*]*\*?\*?\s*([^\n]+)", body, re.IGNORECASE)
        if files_match:
            item["files"] = files_match.group(1).strip()
        else:
            item["files"] = ""

        # Área
        area_match = re.search(r"\*\*Área[:\*]*\*?\*?\s*([^\n]+)", body, re.IGNORECASE)
        if area_match:
            item["area"] = area_match.group(1).strip().strip("`")
        else:
            item["area"] = ""

        # Acceptance criteria
        ac_match = re.search(
            r"\*\*Acceptance criteria[:\*]*\*?\*?\s*\n((?:  - [^\n]+\n?)+)",
            body,
            re.IGNORECASE,
        )
        if ac_match:
            item["acceptance_criteria"] = ac_match.group(1).strip()
        else:
            item["acceptance_criteria"] = ""

        # Slug para branch/filename
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
        item["slug"] = slug

        items.append(item)

    return items


# ---------------------------------------------------------------------------
# Filtros de elegibilidad
# ---------------------------------------------------------------------------


def load_attempted_state() -> dict[str, str]:
    """Carga el state de ítems intentados. Retorna {slug: iso_date_str}."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_attempted_state(state: dict[str, str]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def is_in_cooldown(slug: str, state: dict[str, str]) -> bool:
    """Verifica si el ítem está en período de cooldown."""
    if slug not in state:
        return False
    try:
        last_attempt = datetime.fromisoformat(state[slug])
        cutoff = datetime.now(tz=UTC) - timedelta(days=COOLDOWN_DAYS)
        return last_attempt > cutoff
    except ValueError:
        return False


def has_skip_mark(item: dict[str, object]) -> bool:
    body = str(item.get("body", "")).lower()
    title = str(item.get("title", "")).lower()
    combined = body + " " + title
    return any(mark in combined for mark in SKIP_MARKS)


def touches_denylist(item: dict[str, object]) -> bool:
    files_str = str(item.get("files", "")).lower()
    body_str = str(item.get("body", "")).lower()
    combined = files_str + " " + body_str
    return any(deny.lower() in combined for deny in CODER_PATH_DENYLIST)


def is_eligible(
    item: dict[str, object],
    attempted_state: dict[str, str],
    *,
    require_low_risk: bool = True,
) -> bool:
    priority = str(item.get("priority", ""))
    risk = str(item.get("risk", ""))
    slug = str(item.get("slug", ""))

    if priority not in ("P2", "P3"):
        return False
    if require_low_risk and risk != "bajo":
        return False
    if has_skip_mark(item):
        return False
    if touches_denylist(item):
        return False

    return not is_in_cooldown(slug, attempted_state)


# ---------------------------------------------------------------------------
# Auto-discovery de ítems P3
# ---------------------------------------------------------------------------


def discover_new_items() -> list[dict[str, object]]:
    """Analiza el codebase y genera candidatos P3 para el backlog.

    Busca:
    - TODO/FIXME en código Python
    - Módulos sin docstring de módulo
    - Funciones públicas sin type hints en módulos non-strict
    """
    discovered: list[dict[str, object]] = []

    # 1. TODOs/FIXMEs en .py (excluyendo tests, venv, cache)
    exclude_dirs = {
        ".venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        "node_modules",
        "htmlcov",
    }
    todo_pattern = re.compile(r"#\s*(TODO|FIXME)[:\s](.+)", re.IGNORECASE)

    todos_by_file: dict[str, list[str]] = {}
    for py_file in REPO_ROOT.rglob("*.py"):
        # Saltar directorios excluidos
        parts = set(py_file.parts)
        if parts & {str(REPO_ROOT / d) for d in exclude_dirs}:
            continue
        if any(d in str(py_file) for d in exclude_dirs):
            continue

        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        matches = todo_pattern.findall(content)
        if matches:
            rel = str(py_file.relative_to(REPO_ROOT))
            todos_by_file[rel] = [f"{kind}: {text.strip()}" for kind, text in matches]

    for filepath, todos in list(todos_by_file.items())[:5]:  # máx 5 items de TODOs
        title = f"Resolver TODOs en {filepath}"
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
        todo_list = "\n".join(f"  - {t}" for t in todos[:3])
        discovered.append(
            {
                "title": title,
                "priority": "P3",
                "risk": "bajo",
                "slug": slug,
                "area": filepath.split("/")[0] if "/" in filepath else filepath,
                "files": filepath,
                "acceptance_criteria": f"TODOs/FIXMEs resueltos o documentados:\n{todo_list}",
                "body": f"**Área:** `{filepath.split('/')[0]}`\n**Riesgo:** bajo\n**Files de partida:** [{filepath}](../{filepath})\n**agent:auto-discovered**",
                "auto_discovered": True,
            }
        )

    # 2. Módulos sin docstring de módulo (excl tests, migrations)
    no_docstring: list[str] = []
    for py_file in sorted(REPO_ROOT.rglob("*.py"))[:200]:  # limitar búsqueda
        if any(d in str(py_file) for d in exclude_dirs):
            continue
        if "alembic" in str(py_file) or "tests" in str(py_file):
            continue
        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # Docstring: primera expresión es string literal
        stripped = content.lstrip()
        if stripped and not stripped.startswith(('"""', "'''", "#", 'r"""', "r'''")):
            rel = str(py_file.relative_to(REPO_ROOT))
            # Solo incluir módulos con funciones/clases (no __init__ vacíos)
            if "def " in content or "class " in content:
                no_docstring.append(rel)

    if no_docstring:
        sample = no_docstring[:3]
        title = f"Agregar docstrings de módulo a {len(no_docstring)} archivos (sample: {sample[0]})"
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
        discovered.append(
            {
                "title": title,
                "priority": "P3",
                "risk": "bajo",
                "slug": slug,
                "area": "múltiple",
                "files": ", ".join(f"[{f}](../{f})" for f in sample),
                "acceptance_criteria": f"Al menos {min(5, len(no_docstring))} módulos con docstring de módulo.",
                "body": (
                    f"**Área:** múltiple\n**Riesgo:** bajo\n"
                    f"**Files de partida:** {', '.join(sample)}\n"
                    f"**Módulos sin docstring:** {len(no_docstring)}\n**agent:auto-discovered**"
                ),
                "auto_discovered": True,
            }
        )

    return discovered


def append_items_to_backlog(items: list[dict[str, object]]) -> None:
    """Agrega ítems auto-descubiertos al backlog antes de la sección Cerrados."""
    if not items:
        return

    backlog_text = BACKLOG_PATH.read_text(encoding="utf-8")

    new_entries: list[str] = []
    for item in items:
        title = str(item["title"])
        body = str(item.get("body", ""))
        ac = str(item.get("acceptance_criteria", ""))
        files = str(item.get("files", ""))

        entry = f"\n### {title}\n{body}\n- **Acceptance criteria:**\n  - {ac}\n- **Files de partida:** {files}\n"
        new_entries.append(entry)

    insert_section = "\n## P3 — Auto-discovered\n\n" + "\n".join(new_entries) + "\n"

    # Insertar antes de ## Cerrados
    cerrados_match = re.search(r"^## Cerrados", backlog_text, re.MULTILINE)
    if cerrados_match:
        pos = cerrados_match.start()
        updated = backlog_text[:pos] + insert_section + "\n---\n\n" + backlog_text[pos:]
    else:
        updated = backlog_text.rstrip() + insert_section

    BACKLOG_PATH.write_text(updated, encoding="utf-8")
    print(f"  Auto-discovered: {len(items)} ítems agregados al backlog.", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--list", action="store_true", help="Lista todos los ítems elegibles")
    parser.add_argument("--discover-only", action="store_true", help="Solo auto-descubre, no elige")
    parser.add_argument("--mark-attempted", metavar="SLUG", help="Marca un slug como intentado hoy")
    args = parser.parse_args()

    attempted_state = load_attempted_state()

    # Marcar intentado
    if args.mark_attempted:
        attempted_state[args.mark_attempted] = datetime.now(tz=UTC).isoformat()
        save_attempted_state(attempted_state)
        print(f"Marcado como intentado: {args.mark_attempted}")
        return

    backlog_text = BACKLOG_PATH.read_text(encoding="utf-8")
    all_items = parse_backlog(backlog_text)
    eligible = [i for i in all_items if is_eligible(i, attempted_state)]

    if args.list:
        print(json.dumps(eligible, indent=2, ensure_ascii=False))
        return

    if args.discover_only or not eligible:
        if not eligible:
            print("No hay ítems elegibles en el backlog. Auto-descubriendo...", file=sys.stderr)

        discovered = discover_new_items()
        if discovered:
            append_items_to_backlog(discovered)
            # Re-parsear con los nuevos ítems
            backlog_text = BACKLOG_PATH.read_text(encoding="utf-8")
            all_items = parse_backlog(backlog_text)
            eligible = [i for i in all_items if is_eligible(i, attempted_state)]
        else:
            print("Auto-discovery no encontró candidatos.", file=sys.stderr)

        if args.discover_only:
            return

    if not eligible:
        print("ERROR: No hay ítems elegibles ni auto-descubiertos.", file=sys.stderr)
        sys.exit(1)

    # Elegir el primero (P2 antes que P3, orden de aparición en el backlog)
    priority_order = {"P2": 0, "P3": 1}
    eligible_sorted = sorted(
        eligible, key=lambda i: priority_order.get(str(i.get("priority", "P3")), 2)
    )
    chosen = eligible_sorted[0]

    # Output JSON para que el workflow lo consuma
    output = {
        "slug": chosen["slug"],
        "title": chosen["title"],
        "priority": chosen["priority"],
        "risk": chosen["risk"],
        "area": chosen["area"],
        "files": chosen["files"],
        "acceptance_criteria": chosen["acceptance_criteria"],
        "auto_discovered": chosen.get("auto_discovered", False),
    }
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
