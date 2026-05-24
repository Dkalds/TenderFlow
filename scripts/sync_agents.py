#!/usr/bin/env python3
"""
sync_agents.py — Sincroniza docs/agents/<role>.md a formatos por-tool.

Genera:
  - .claude/agents/<role>.md       (Claude Code subagent format)
  - .opencode/agents/<role>.md     (OpenCode markdown agent format)
  - Sección en .github/copilot-instructions.md (entre markers AGENTS-SYNC)

Uso:
  python scripts/sync_agents.py              # regenera todo
  python scripts/sync_agents.py --check      # sale con 1 si hay drift (CI)
  python scripts/sync_agents.py --role coder # regenera solo un rol
"""

from __future__ import annotations

import argparse
import re
import sys
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
CANON_DIR = REPO_ROOT / "docs" / "agents"
CLAUDE_AGENTS_DIR = REPO_ROOT / ".claude" / "agents"
OPENCODE_AGENTS_DIR = REPO_ROOT / ".opencode" / "agents"
COPILOT_INSTRUCTIONS = REPO_ROOT / ".github" / "copilot-instructions.md"

SYNC_START = "<!-- AGENTS-SYNC:START -->"
SYNC_END = "<!-- AGENTS-SYNC:END -->"

# Mapping model_tier → IDs por tool
# Proveedor: GitHub Copilot (no requiere ANTHROPIC_API_KEY, usa GITHUB_TOKEN).
# Actualizar aquí cuando salgan nuevas versiones de modelos.
MODEL_TIER_TO_CLAUDE_CODE: dict[str, str] = {
    "opus": "github-copilot/claude-opus-4.6",
    "sonnet": "github-copilot/claude-sonnet-4.6",
    "haiku": "github-copilot/claude-haiku-4.5",
}

MODEL_TIER_TO_OPENCODE: dict[str, str] = {
    "opus": "github-copilot/claude-opus-4.6",
    "sonnet": "github-copilot/claude-sonnet-4.6",
    "haiku": "github-copilot/claude-haiku-4.5",
}

# Mapping tool_class → tools para Claude Code
TOOL_CLASS_TO_CLAUDE_TOOLS: dict[str, str] = {
    "read_only": "Read, Grep, Glob, Bash",
    "write_code": "Read, Grep, Glob, Edit, Write, Bash",
    "write_tests": "Read, Grep, Glob, Edit, Write, Bash",
    "write_docs": "Read, Grep, Glob, Write, Bash",
    "orchestrate": "Task, Read, Grep, Glob, Bash",
}

# Mapping tool_class → permission block para OpenCode
# Cada valor es un dict listo para serializar a YAML manual.
TOOL_CLASS_TO_OPENCODE_PERMISSION: dict[str, str] = {
    "read_only": textwrap.dedent("""\
        permission:
          edit: deny
          bash:
            "*": ask
            "git diff *": allow
            "git log *": allow
            "git show *": allow
            "git status": allow
            "gh pr view *": allow
            "gh issue view *": allow
            "ruff check --no-fix *": allow
            "mypy --no-error-summary *": allow
            "bandit *": allow
            "graphify *": allow
            "grep *": allow
            "cat *": allow
          task: deny
          webfetch: deny
    """),
    "write_code": textwrap.dedent("""\
        permission:
          edit: allow
          bash:
            "*": allow
            "git push *": deny
            "gh pr create *": deny
            "gh pr merge *": deny
            "gh pr close *": deny
            "alembic *": deny
            "rm -rf *": deny
          task: deny
          webfetch: deny
    """),
    "write_tests": textwrap.dedent("""\
        permission:
          edit:
            "tests/**": allow
            "*": deny
          bash:
            "*": allow
            "git push *": deny
            "gh pr create *": deny
            "alembic *": deny
            "rm -rf *": deny
          task: deny
          webfetch: deny
    """),
    "write_docs": textwrap.dedent("""\
        permission:
          edit:
            "docs/rfc/**": allow
            "docs/adr/discussions/**": allow
            "*": deny
          bash:
            "*": ask
            "graphify *": allow
            "grep *": allow
            "git log *": allow
            "git diff *": allow
            "gh issue view *": allow
          task: deny
          webfetch: deny
    """),
    "orchestrate": textwrap.dedent("""\
        permission:
          edit: deny
          bash:
            "*": allow
            "git push *": deny
            "gh pr merge *": deny
            "gh pr close *": deny
            "alembic *": deny
            "rm -rf *": deny
          task: allow
          webfetch: deny
    """),
}

# steps (max iteraciones agenticas) por tool_class
TOOL_CLASS_TO_STEPS: dict[str, int] = {
    "orchestrate": 60,
    "write_code": 40,
    "write_tests": 30,
    "write_docs": 20,
    "read_only": 20,
}


# ---------------------------------------------------------------------------
# Parser del frontmatter YAML manual (sin dependencias externas)
# ---------------------------------------------------------------------------


def parse_frontmatter(content: str) -> tuple[dict[str, object], str]:
    """Parsea frontmatter YAML simple de un archivo markdown.

    Soporta: strings, listas de strings con guión, booleans.
    Retorna (dict_frontmatter, body_sin_frontmatter).
    """
    if not content.startswith("---\n"):
        return {}, content

    end = content.find("\n---\n", 4)
    if end == -1:
        return {}, content

    fm_text = content[4:end]
    body = content[end + 5 :]  # skip \n---\n

    meta: dict[str, object] = {}
    current_list_key: str | None = None

    for line in fm_text.splitlines():
        # list item
        if line.startswith("  - ") and current_list_key:
            cast_list = meta[current_list_key]
            assert isinstance(cast_list, list)
            cast_list.append(line[4:].strip())
            continue

        if ":" not in line:
            current_list_key = None
            continue

        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()

        if val == "":
            # Siguiente líneas serán lista
            meta[key] = []
            current_list_key = key
        else:
            current_list_key = None
            # bool
            if val.lower() == "true":
                meta[key] = True
            elif val.lower() == "false":
                meta[key] = False
            else:
                meta[key] = val

    return meta, body


# ---------------------------------------------------------------------------
# Generadores por tool
# ---------------------------------------------------------------------------


def generate_claude_agent(meta: dict[str, object], body: str) -> str:
    """Genera el contenido para .claude/agents/<role>.md."""
    role = str(meta.get("role", "unknown"))
    description = str(meta.get("description", ""))
    model_tier = str(meta.get("model_tier", "sonnet"))
    tool_class = str(meta.get("tool_class", "read_only"))

    model = MODEL_TIER_TO_CLAUDE_CODE.get(model_tier, "claude-sonnet-4-5")
    tools = TOOL_CLASS_TO_CLAUDE_TOOLS.get(tool_class, "Read, Grep, Glob, Bash")

    path_denylist = meta.get("path_denylist", [])
    denylist_comment = ""
    if isinstance(path_denylist, list) and path_denylist:
        denylist_comment = "\n".join(f"# denylist: {p}" for p in path_denylist)
        denylist_comment = f"\n{denylist_comment}"

    fm = f"""---
name: {role}
description: {description}
model: {model}
tools: {tools}
---
"""
    return fm + denylist_comment + "\n" + body.lstrip()


def generate_opencode_agent(meta: dict[str, object], body: str) -> str:
    """Genera el contenido para .opencode/agents/<role>.md."""
    description = str(meta.get("description", ""))
    model_tier = str(meta.get("model_tier", "sonnet"))
    tool_class = str(meta.get("tool_class", "read_only"))

    model = MODEL_TIER_TO_OPENCODE.get(model_tier, "anthropic/claude-sonnet-4-20250514")
    steps = TOOL_CLASS_TO_STEPS.get(tool_class, 20)
    permission_block = TOOL_CLASS_TO_OPENCODE_PERMISSION.get(tool_class, "")

    fm = f"""---
description: {description}
mode: subagent
model: {model}
temperature: 0.1
steps: {steps}
{permission_block.rstrip()}
---
"""
    return fm + "\n" + body.lstrip()


def generate_copilot_section(all_meta: list[dict[str, object]]) -> str:
    """Genera la sección completa para copilot-instructions.md."""
    lines = [
        "## Perfiles de trabajo (sincronizado desde docs/agents/)",
        "",
        "Copilot no soporta subagentes nativos. Al iniciar un chat con un rol específico,",
        "prepend el prompt correspondiente para activar el comportamiento del rol.",
        "",
    ]

    role_order = [
        "orchestrator",
        "architect",
        "coder",
        "test_engineer",
        "reviewer",
        "security_triage",
    ]
    meta_by_role = {str(m.get("role", "")): m for m in all_meta}

    for role in role_order:
        m = meta_by_role.get(role)
        if not m:
            continue

        description = str(m.get("description", ""))
        path_denylist = m.get("path_denylist", [])
        tool_class = str(m.get("tool_class", "read_only"))

        # Nombre display
        display = role.replace("_", " ").title()

        lines.append(f"### {display}")
        lines.append("")
        lines.append(
            f"Sos el rol **{role}** definido en `docs/agents/{role}.md`. "
            f"Leé ese archivo y `AGENTS.md` §3 antes de proponer cualquier cambio."
        )

        if tool_class == "read_only":
            lines.append("**Modo read-only**: solo comentarios y sugerencias, sin editar archivos.")
        elif tool_class == "orchestrate":
            lines.append(
                "**Modo orchestrator**: no edites archivos directamente; coordina y delega."
            )
        elif tool_class == "write_docs":
            lines.append(
                "**Escribe solo en** `docs/rfc/**` y `docs/adr/discussions/**`. "
                "Read-only sobre código fuente."
            )

        if isinstance(path_denylist, list) and path_denylist:
            denylist_str = ", ".join(f"`{p}`" for p in path_denylist[:6])
            suffix = f" (y {len(path_denylist) - 6} más)" if len(path_denylist) > 6 else ""
            lines.append(f"**No editar**: {denylist_str}{suffix}.")

        lines.append(f"*{description}*")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def load_canon_file(path: Path) -> tuple[dict[str, object], str]:
    content = path.read_text(encoding="utf-8")
    return parse_frontmatter(content)


def write_if_changed(path: Path, content: str, check_mode: bool) -> bool:
    """Escribe el archivo si cambió. En check_mode solo verifica. Retorna True si hubo drift."""
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing == content:
            return False  # no drift

    if check_mode:
        print(f"  DRIFT: {path.relative_to(REPO_ROOT)}", file=sys.stderr)
        return True

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  wrote: {path.relative_to(REPO_ROOT)}")
    return False


def update_copilot_instructions(section: str, check_mode: bool) -> bool:
    """Inserta/actualiza la sección entre los markers en copilot-instructions.md."""
    if not COPILOT_INSTRUCTIONS.exists():
        if check_mode:
            print(
                f"  DRIFT: {COPILOT_INSTRUCTIONS.relative_to(REPO_ROOT)} (no existe)",
                file=sys.stderr,
            )
            return True
        # Crear con markers
        content = (
            "# Copilot Instructions\n\n"
            "Ver `AGENTS.md` como fuente canónica de instrucciones para todos los agentes.\n\n"
            f"{SYNC_START}\n{section}\n{SYNC_END}\n"
        )
        COPILOT_INSTRUCTIONS.parent.mkdir(parents=True, exist_ok=True)
        COPILOT_INSTRUCTIONS.write_text(content, encoding="utf-8")
        print(f"  wrote: {COPILOT_INSTRUCTIONS.relative_to(REPO_ROOT)}")
        return False

    original = COPILOT_INSTRUCTIONS.read_text(encoding="utf-8")

    if SYNC_START in original and SYNC_END in original:
        # Reemplazar entre markers
        pattern = re.compile(
            re.escape(SYNC_START) + r".*?" + re.escape(SYNC_END),
            re.DOTALL,
        )
        new_block = f"{SYNC_START}\n{section}\n{SYNC_END}"
        updated = pattern.sub(new_block, original)
    else:
        # Insertar markers al final
        updated = original.rstrip() + f"\n\n{SYNC_START}\n{section}\n{SYNC_END}\n"

    return write_if_changed(COPILOT_INSTRUCTIONS, updated, check_mode)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def sync_role(role_path: Path, check_mode: bool) -> bool:
    """Sincroniza un archivo canon a todos los formatos. Retorna True si hubo drift."""
    meta, body = load_canon_file(role_path)
    role = str(meta.get("role", role_path.stem))

    drift = False

    # Claude Code
    claude_content = generate_claude_agent(meta, body)
    drift |= write_if_changed(CLAUDE_AGENTS_DIR / f"{role}.md", claude_content, check_mode)

    # OpenCode
    opencode_content = generate_opencode_agent(meta, body)
    drift |= write_if_changed(OPENCODE_AGENTS_DIR / f"{role}.md", opencode_content, check_mode)

    return drift


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--check", action="store_true", help="Solo verifica drift, no escribe (para CI)"
    )
    parser.add_argument("--role", help="Sincronizar solo este rol (ej: coder)")
    args = parser.parse_args()

    check_mode: bool = args.check
    target_role: str | None = args.role

    if not CANON_DIR.exists():
        print(f"ERROR: directorio canon no encontrado: {CANON_DIR}", file=sys.stderr)
        sys.exit(1)

    # Recolectar archivos canon
    canon_files = sorted(CANON_DIR.glob("*.md"))
    if not canon_files:
        print(f"ERROR: no hay archivos .md en {CANON_DIR}", file=sys.stderr)
        sys.exit(1)

    if target_role:
        canon_files = [f for f in canon_files if f.stem == target_role]
        if not canon_files:
            print(f"ERROR: rol '{target_role}' no encontrado en {CANON_DIR}", file=sys.stderr)
            sys.exit(1)

    print(f"{'Verificando' if check_mode else 'Sincronizando'} {len(canon_files)} roles...")

    total_drift = False

    for canon_path in canon_files:
        role_name = canon_path.stem
        print(f"\n[{role_name}]")
        total_drift |= sync_role(canon_path, check_mode)

    # Actualizar sección Copilot (solo si sincronizamos todos)
    if not target_role:
        print("\n[copilot-instructions]")
        all_meta = []
        for canon_path in canon_files:
            meta, _ = load_canon_file(canon_path)
            all_meta.append(meta)
        section = generate_copilot_section(all_meta)
        total_drift |= update_copilot_instructions(section, check_mode)

    if check_mode:
        if total_drift:
            print(
                "\nERROR: hay drift entre docs/agents/ y los archivos generados.",
                file=sys.stderr,
            )
            print("Ejecuta: python scripts/sync_agents.py", file=sys.stderr)
            sys.exit(1)
        else:
            print("\nOK: sin drift.")
    else:
        print("\nSync completado.")


if __name__ == "__main__":
    main()
