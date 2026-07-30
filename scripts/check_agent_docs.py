"""Verifica que las instrucciones de agentes describan el repo real.

Valida, sobre `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`,
`docs/AGENT_PLAYBOOK.md`, `docs/graphify-first.md` y las configs de cada
herramienta (`.claude/`, `.agents/`, `.codex/`, `.opencode/`):

1. Todo `make <target>` citado existe en el Makefile.
2. Todo slash-command citado existe en `.claude/commands/`.
3. Los skills nombrados en CLAUDE.md existen en `.claude/skills/` y son
   invocables por el modelo.
4. `.claude/skills/` y `.agents/skills/` contienen todo lo que declara
   `skills-lock.json` (los dos árboles no divergen).
5. Toda ruta del repo citada entre backticks o como link markdown existe.
6. Los hooks apuntan a scripts existentes y sin rutas absolutas de una máquina.
7. Los comandos de `.claude/commands/` y sus copias
   `.agents/skills/source-command-*/` no divergen.
8. No quedan wikilinks de Obsidian anidados dentro de links markdown.

Uso: python scripts/check_agent_docs.py [--verbose]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

INSTRUCTION_FILES = [
    "AGENTS.md",
    "CLAUDE.md",
    "web/AGENTS.md",
    ".github/copilot-instructions.md",
    "docs/AGENT_PLAYBOOK.md",
    "docs/graphify-first.md",
    "docs/contributor-checklist.md",
    ".agents/rules/graphify.md",
]

COMMANDS_DIR = ROOT / ".claude/commands"
CLAUDE_SKILLS = ROOT / ".claude/skills"
AGENTS_SKILLS = ROOT / ".agents/skills"

# Tokens que parecen slash-command pero no lo son.
SLASH_ALLOWLIST = {"/api", "/ask", "/me", "/competitive", "/analytics", "/graphify"}

# Rutas citadas que son ejemplos o plantillas, no archivos reales.
PATH_ALLOWLIST = {
    "graphify-out/wiki/index.md",  # lo genera el CLI, opcional
    "graphify-out/wiki/",
    "graphify-out/GRAPH_REPORT.md",
    "graphify-out/.graph_stale",
    "graphify-out/graph.json",
}

ABSOLUTE_PATH_PATTERNS = [
    re.compile(r"[A-Za-z]:\\\\"),  # C:\... escapado en JSON
    re.compile(r"[A-Za-z]:\\[A-Za-z]"),  # C:\...
    re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
]

BACKTICK = re.compile(r"`([^`\n]+)`")
LINK_TARGET = re.compile(r"\]\(([^)\s]+)\)")
MAKE_CALL = re.compile(r"\bmake\s+([a-z][a-z0-9-]*)(?![a-z0-9*-])")
HOOK_SCRIPT = re.compile(r"(\.claude|\.codex)/hooks/([\w-]+\.py)")
FRONTMATTER_NAME = re.compile(r"^name:\s*[\"']?([^\"'\n]+)[\"']?", re.MULTILINE)

errors: list[str] = []
warnings: list[str] = []


def fail(where: str, msg: str) -> None:
    errors.append(f"{where}: {msg}")


def warn(where: str, msg: str) -> None:
    warnings.append(f"{where}: {msg}")


def read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def make_targets() -> set[str]:
    text = read("Makefile")
    return set(re.findall(r"^([a-z][a-z0-9-]*):", text, re.MULTILINE))


def looks_like_path(token: str) -> bool:
    if any(c in token for c in "*?{}<>$ |"):
        return False
    if token.startswith(("http", "mailto:", "#")):
        return False
    # Dependencias instaladas: existen o no según el entorno, no según el doc.
    if token.startswith("node_modules/") or "/node_modules/" in token:
        return False
    # `competitive/`, `wiki/`: un solo segmento, se lee relativo al paquete que
    # menciona la prosa alrededor. No es una ruta resoluble desde la raíz.
    if "/" not in token.rstrip("/"):
        return False
    return bool(re.search(r"\.[a-z]{1,5}$", token) or token.endswith("/"))


def check_make_targets(targets: set[str]) -> None:
    sources = [
        *INSTRUCTION_FILES,
        *(f".claude/commands/{p.name}" for p in sorted(COMMANDS_DIR.glob("*.md"))),
    ]
    for rel in sources:
        for target in set(MAKE_CALL.findall(read(rel))):
            if target not in targets:
                fail(rel, f"cita `make {target}`, que no existe en el Makefile")


def check_slash_commands() -> None:
    available = {f"/{p.stem}" for p in COMMANDS_DIR.glob("*.md")}
    for rel in INSTRUCTION_FILES:
        for token in set(BACKTICK.findall(read(rel))):
            name = token.split()[0]
            if not re.fullmatch(r"/[a-z][a-z0-9-]*", name):
                continue
            if name in SLASH_ALLOWLIST or name in available:
                continue
            fail(rel, f"cita el slash-command `{name}`, que no existe en .claude/commands/")


def skill_is_model_invocable(skill_dir: Path) -> bool:
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8", errors="replace")
    head = text.split("---", 2)[1] if text.startswith("---") else ""
    return "disable-model-invocation: true" not in head


def check_claude_skills() -> None:
    """Valida los nombres de skill citados en frases que hablan de skills."""
    sentences = [s for s in re.split(r"(?<=[.:])\s", read("CLAUDE.md")) if "skill" in s.lower()]
    if not sentences:
        warn("CLAUDE.md", "no menciona skills; no se validó ningún nombre")
        return
    for sentence in sentences:
        # Los skills de referencia se nombran en la frase que explica por qué no
        # se invocan; ahí `disable-model-invocation: true` es esperado.
        reference_only = "disable-model-invocation" in sentence
        # Una frase que afirma que un skill NO existe se valida al revés: si
        # alguien lo crea, la afirmación pasa a ser falsa y hay que actualizarla.
        negated = "no existe" in sentence.lower()
        for token in BACKTICK.findall(sentence):
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", token):
                continue
            skill = CLAUDE_SKILLS / token
            exists = (skill / "SKILL.md").exists()
            if negated:
                if exists:
                    fail(
                        "CLAUDE.md",
                        f"afirma que el skill `{token}` no existe, pero .claude/skills/{token} sí está",
                    )
            elif not exists:
                fail("CLAUDE.md", f"nombra el skill `{token}`, que no existe en .claude/skills/")
            elif not reference_only and not skill_is_model_invocable(skill):
                fail(
                    "CLAUDE.md",
                    f"presenta `{token}` como invocable, pero tiene disable-model-invocation: true",
                )


def check_skill_trees() -> None:
    lock_path = ROOT / "skills-lock.json"
    if not lock_path.exists():
        return
    lock = json.loads(lock_path.read_text(encoding="utf-8")).get("skills", {})
    for name in sorted(lock):
        for tree in (CLAUDE_SKILLS, AGENTS_SKILLS):
            if not (tree / name / "SKILL.md").exists():
                fail(
                    "skills-lock.json",
                    f"declara `{name}` pero falta en {tree.relative_to(ROOT)}/ (los dos árboles deben coincidir)",
                )
    reported: set[str] = set()
    for tree in (CLAUDE_SKILLS, AGENTS_SKILLS):
        for skill in sorted(tree.glob("*/SKILL.md")):
            declared = FRONTMATTER_NAME.search(skill.read_text(encoding="utf-8", errors="replace"))
            name = declared.group(1).strip() if declared else skill.parent.name
            if name != skill.parent.name and skill.parent.name not in reported:
                reported.add(skill.parent.name)
                warn(
                    f"skills/{skill.parent.name}",
                    f"frontmatter name '{name}' != directorio (vendored upstream; el modelo lo indexa por frontmatter)",
                )


def check_paths() -> None:
    for rel in INSTRUCTION_FILES:
        text = read(rel)
        base = (ROOT / rel).parent
        for token in set(BACKTICK.findall(text)):
            token = token.strip().rstrip(",.;:")
            if not looks_like_path(token) or token in PATH_ALLOWLIST:
                continue
            if not (ROOT / token).exists():
                fail(rel, f"cita la ruta `{token}`, que no existe")
        for target in set(LINK_TARGET.findall(text)):
            target = target.split("#")[0]
            if not target or target.startswith(("http", "mailto:")) or "*" in target:
                continue
            if not (base / target).exists():
                fail(rel, f"link roto: {target}")


def check_hooks_and_absolute_paths() -> None:
    configs = [
        ".claude/settings.json",
        ".codex/hooks.json",
        ".opencode/opencode.json",
        *INSTRUCTION_FILES,
    ]
    for rel in configs:
        text = read(rel)
        if not text:
            continue
        for pattern in ABSOLUTE_PATH_PATTERNS:
            if pattern.search(text):
                fail(
                    rel,
                    "contiene una ruta absoluta de una máquina concreta (usá la variable de proyecto)",
                )
                break
        for tool_dir, script in set(HOOK_SCRIPT.findall(text)):
            if not (ROOT / tool_dir / "hooks" / script).exists():
                fail(rel, f"referencia el hook {tool_dir}/hooks/{script}, que no existe")
    for rel in (".claude/settings.json", ".codex/hooks.json"):
        text = read(rel)
        if text and "python" in text and "hooks/" not in text:
            warn(rel, "define hooks sin apuntar a .../hooks/*.py")


def check_command_copies() -> None:
    for command in sorted(COMMANDS_DIR.glob("*.md")):
        copy = AGENTS_SKILLS / f"source-command-{command.stem}/SKILL.md"
        if not copy.exists():
            continue
        body = command.read_text(encoding="utf-8").split("---", 2)[-1]
        copy_text = copy.read_text(encoding="utf-8")
        missing = [
            ln.strip() for ln in body.splitlines() if ln.strip() and ln.strip() not in copy_text
        ]
        if missing:
            fail(
                str(copy.relative_to(ROOT)),
                f"divergió de {command.relative_to(ROOT)} ({len(missing)} línea/s), p.ej.: {missing[0][:80]!r}",
            )


def check_nested_wikilinks() -> None:
    files = [ROOT / rel for rel in INSTRUCTION_FILES] + sorted((ROOT / "docs").rglob("*.md"))
    for path in files:
        if not path.exists():
            continue
        for target in LINK_TARGET.findall(path.read_text(encoding="utf-8")):
            if "[[" in target:
                fail(
                    str(path.relative_to(ROOT)),
                    f"wikilink anidado dentro de un link markdown: {target}",
                )


def main() -> int:
    verbose = "--verbose" in sys.argv
    targets = make_targets()
    check_make_targets(targets)
    check_slash_commands()
    check_claude_skills()
    check_skill_trees()
    check_paths()
    check_hooks_and_absolute_paths()
    check_command_copies()
    check_nested_wikilinks()

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")

    if errors:
        print(f"\n{len(errors)} problema/s en las instrucciones de agentes.")
        return 1
    if verbose:
        print(f"Targets del Makefile conocidos: {len(targets)}")
    print(f"Instrucciones de agentes consistentes ({len(warnings)} warning/s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
